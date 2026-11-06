// 组织的真实逻辑：发布带的形态、与本项目的改动合成、结构校验、摘要版本、成果怎么走、差异、草稿、采用、冻结。
// 别的页面都从这里读，不写死结果。这个文件不碰页面，可以单独拿到 Node 里跑。
(function () {
  'use strict';
  const Y19 = window.Y19;
  const O = Y19.org = {};

  const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const uniq = (a) => a.filter((x, i) => a.indexOf(x) === i);

  O.MAX_DEPTH = 2; // 子组织的嵌套深度上限（循环与收敛设计说明：现值为 2）
  O.ROTATIONS = { by_outcome: '按成果', direct: '直做', pool: '任务池' };
  O.ROTATION_NOTE = {
    by_outcome: '每个部门关注哪些成果，成果交出来就轮到谁',
    direct: '一个角色接到你的输入、指导或询问就开工，自己交完成',
    pool: '工作拆成单元放进池子，空闲的角色来领'
  };
  O.WRITE = { workspace: '运行工作区', check_only: '只写检查材料', none: '不写入' };
  O.WHO = { own: '自有角色', outsourced: '外包', suborg: '子组织' };
  O.AGENTS = ['OpenCode', 'Claude Code'];
  O.BUILTIN = {}; // 事项的来源不再混在「关注的成果」里，来源写在形态的 sources 里

  // ------------------------------------------------------------------ 发布带的目录

  const TOOLS = [['读文件', '文件'], ['写文件', '文件'], ['运行命令', '命令'], ['取回网页', '网络'], ['浏览器操作', '浏览器与桌面'], ['桌面操作', '浏览器与桌面'],
    ['只读数据库（MCP）', 'MCP 工具'], ['数据仓库查询（MCP）', 'MCP 工具'], ['串口与烧录（MCP）', 'MCP 工具'], ['迁移脚本检查', '文件']];
  let release = { addTools: false, dropTools: [] };
  O.setRelease = (r) => { release = Object.assign({ addTools: false, dropTools: [] }, r || {}); };
  O.release = () => release;
  O.catalog = () => TOOLS.filter((t) => (t[0] !== '迁移脚本检查' || release.addTools) && !release.dropTools.includes(t[0]));
  O.toolNames = () => O.catalog().map((t) => t[0]);

  O.MODELS = { 'deepseek-v3.2': { vision: false }, 'qwen3-coder-plus': { vision: false }, 'glm-4.6v': { vision: true }, 'qwen3.6-plus': { vision: true }, 'kimi-k2.6': { vision: true } };
  O.modelChoices = () => Object.keys(O.MODELS).concat(Y19.readyModels ? Y19.readyModels().filter((m) => !O.MODELS[m]) : []);

  O.OBSERVERS = {
    lessons: { id: 'lessons', name: '教训发现', makes: '证据、提案', scopes: ['缺陷记录与返工', '缺陷记录、返工与询问'], recent: '3 条教训证据，最近一条今天 11:20', on: false },
    oscillation: { id: 'oscillation', name: '振荡检测', makes: '振荡信号', scopes: ['各事项的收敛状态', '只看进行中的事项'], recent: '1 个振荡信号，昨天 20:15', on: false },
    meta: { id: 'meta', name: '元观察', makes: '提案', scopes: ['组织与规则的运行证据'], recent: '还没有产出', on: false }
  };
  const obsDefault = () => ['lessons', 'oscillation', 'meta'].map((id) => { const o = clone(O.OBSERVERS[id]); o.scope = o.scopes[0]; return o; });

  const D = (o) => Object.assign({ verifies: null, who: { type: 'own' }, completes: false, roles: [], visible: [], model: '' }, o);
  const RAW = {
    three: {
      id: 'three', tip: '默认选项：质检核验，放行才结束', name: '三部门', note: '产品、工程、质检各一个角色，按成果流转，质检放行才算完成',
      rotation: 'by_outcome', adopt: 'delivery', unit: '',
      sources: [{ id: 'input', name: '你的输入', to: 'product' }, { id: 'intake', name: '建档', to: 'product' }],
      outcomes: [
        { id: 'prd', name: 'PRD', desc: '产品写的需求说明，工程照着做', basedOn: 'input', receipt: false, snapshot: false },
        { id: 'delivery', name: '交付', desc: '工程交出的代码与说明', basedOn: 'prd', receipt: false, snapshot: true },
        { id: 'defect', name: '缺陷记录', desc: '质检发现的问题与证据', basedOn: 'delivery', receipt: true, snapshot: false }
      ],
      depts: [
        D({ id: 'product', name: '产品', goal: '把你的输入变成工程能照着做的需求', judge: '你的输入原文和已采纳的成果', how: '读输入、回答工程的询问、写出 PRD 并随输入更新',
          watches: [], produces: ['prd'], write: 'none', tools: ['读文件', '取回网页'], roles: ['产品经理'], visible: ['你的输入', 'PRD', '已采纳的成果'] }),
        D({ id: 'engineering', name: '工程', goal: '按 PRD 做出可交付的代码与说明', judge: '质检的缺陷记录和自己跑的测试', how: '读 PRD、改代码、跑测试、交出交付，按缺陷记录返工',
          watches: ['prd', 'defect'], produces: ['delivery'], write: 'workspace', tools: ['读文件', '写文件', '运行命令', '取回网页'], roles: ['工程师'], visible: ['PRD', '缺陷记录', '运行工作区'] }),
        D({ id: 'quality', name: '质检', goal: '独立核验交付是否满足验收条件', judge: '在独立副本上运行检查得到的证据', how: '先看事实、下结论，再看被核验方的解释；通过就放行，不通过写缺陷记录',
          watches: ['prd', 'delivery'], produces: ['defect'], verifies: { dept: 'engineering', kind: 'delivery' }, write: 'check_only', tools: ['读文件', '运行命令', '浏览器操作', '桌面操作'], roles: ['质检员'], visible: ['PRD', '交付快照', '检查材料'] })
      ],
      observers: obsDefault()
    },
    one_own: {
      id: 'one_own', tip: '一个自有角色，用工程的名字、工具与模型设置；没有核验角色，交完成就结束', name: '一个角色直做', note: '一个部门一个自有角色，接到输入就做，交完成就结束，没有核验角色',
      rotation: 'direct', adopt: '', unit: '',
      sources: [{ id: 'input', name: '你的输入', to: 'engineering' }, { id: 'intake', name: '建档', to: 'engineering' }],
      outcomes: [{ id: 'done', name: '交完成', desc: '角色交出的结果和完成声明', basedOn: 'input', receipt: false, snapshot: true }],
      depts: [D({ id: 'engineering', name: '工程', goal: '一个角色把事情从头做到完成', judge: '自己跑的检查', how: '读输入、动手做、自己检查、交完成',
        watches: [], produces: ['done'], completes: true, write: 'workspace', tools: ['读文件', '写文件', '运行命令', '取回网页'], roles: ['通才'], visible: ['你的输入', '指导', '运行工作区'] })],
      observers: obsDefault()
    },
    one_out: {
      id: 'one_out', tip: '工程是一个外包角色，建好以后在工程的部门详情里选外部 agent（默认 OpenCode）', name: '一个外包角色直做', note: '一个部门一个外包角色，交回快照与差异，以开环完成结束并注明外包',
      rotation: 'direct', adopt: '', unit: '',
      sources: [{ id: 'input', name: '你的输入', to: 'engineering' }, { id: 'intake', name: '建档', to: 'engineering' }],
      outcomes: [{ id: 'snapshot', name: '交回快照', desc: '外部 agent 交回的快照与差异', basedOn: 'input', receipt: false, snapshot: true }],
      depts: [D({ id: 'engineering', name: '工程', goal: '把任务交给外部 agent，收回快照与差异', judge: '外部 agent 交回的快照和差异', how: '给外部 agent 一份没有历史的快照，收回结果，经写入口成为提案',
        watches: [], produces: ['snapshot'], completes: true, who: { type: 'outsourced', agent: 'OpenCode' }, write: 'workspace', tools: ['读文件', '写文件', '运行命令'], roles: ['外部 agent'], visible: ['你的输入', '指导', '运行工作区'] })],
      observers: obsDefault()
    },
    several: {
      id: 'several', tip: '产品、工程两个自有角色，靠询问交流；没有核验角色，可以以后加一个', name: '几个角色直做', note: '产品、工程两个自有角色，靠询问交流；工程接输入、交完成，产品回答询问；没有核验角色，可以以后加一个',
      rotation: 'direct', adopt: '', unit: '',
      sources: [{ id: 'input', name: '你的输入', to: 'engineering' }, { id: 'intake', name: '建档', to: 'engineering' }],
      outcomes: [{ id: 'done', name: '交完成', desc: '工程交出的结果和完成声明', basedOn: 'input', receipt: false, snapshot: true }],
      depts: [
        D({ id: 'product', name: '产品', goal: '回答工程关于需求边界与取舍的询问', judge: '你的输入原文和已采纳的成果', how: '工程拿不准需求时回答它的询问，说清楚做什么、不做什么',
          watches: [], produces: [], write: 'none', tools: ['读文件', '取回网页'], roles: ['产品经理'], visible: ['你的输入', '已采纳的成果'] }),
        D({ id: 'engineering', name: '工程', goal: '按你的输入做出可交付的结果，拿不准的需求去问产品', judge: '自己跑的检查和产品的回答', how: '读输入、动手做、需要时询问产品、自己检查、交完成',
          watches: [], produces: ['done'], completes: true, write: 'workspace', tools: ['读文件', '写文件', '运行命令', '取回网页'], roles: ['工程师'], visible: ['你的输入', '指导', '运行工作区'] })
      ],
      observers: obsDefault()
    },
    hub: {
      id: 'hub', name: '中心型小组', note: '工程架构师居中，主程和探索者是同伴，审查者是这个小组的核验角色；给部门内部用',
      rotation: 'by_outcome', adopt: 'patch', unit: '',
      sources: [{ id: 'task', name: '上一层交来的任务', to: 'architect' }],
      outcomes: [
        { id: 'plan', name: '计划', desc: '架构师拆出的步骤', basedOn: 'input', receipt: false, snapshot: false },
        { id: 'findings', name: '调研结论', desc: '探索者交回的结论', basedOn: 'plan', receipt: false, snapshot: false },
        { id: 'patch', name: '改动', desc: '主程写出的改动', basedOn: 'plan', receipt: false, snapshot: true },
        { id: 'review', name: '审查意见', desc: '审查者对改动的意见', basedOn: 'patch', receipt: true, snapshot: false }
      ],
      depts: [
        D({ id: 'architect', name: '工程架构师', goal: '规划部门这一轮的工作并保管主要上下文', judge: '计划能否被主程照着做、调研结论是否可靠', how: '拆步骤、分给主程和探索者、汇总他们交回的结论',
          watches: ['findings', 'review'], produces: ['plan'], write: 'none', tools: ['读文件'], roles: ['工程架构师'] }),
        D({ id: 'lead', name: '主程', goal: '按计划写出改动', judge: '计划和审查意见', how: '读计划、改代码、跑测试、交出改动',
          watches: ['plan', 'review'], produces: ['patch'], write: 'workspace', tools: ['读文件', '写文件', '运行命令'], roles: ['主程'] }),
        D({ id: 'explorer', name: '探索者', goal: '查清架构师要问的问题', judge: '读到的代码与文档', how: '读代码、查资料、把结论交回架构师',
          watches: ['plan'], produces: ['findings'], write: 'none', tools: ['读文件', '取回网页'], roles: ['探索者'] }),
        D({ id: 'reviewer', name: '审查者', goal: '独立审查主程的改动', judge: '在独立副本上运行检查得到的证据', how: '先看事实再下结论；通过就放行，不通过写审查意见',
          watches: ['patch'], produces: ['review'], verifies: { dept: 'lead', kind: 'patch' }, write: 'check_only', tools: ['读文件', '运行命令'], roles: ['审查者'] })
      ],
      observers: []
    }
  };
  O.PUBLISHED = ['one_out', 'one_own', 'several', 'three'];
  O.form = (id) => {
    const f = RAW[id];
    if (!f) return null;
    const c = clone(f);
    if (release.addTools && id === 'three') c.depts.find((d) => d.id === 'engineering').tools.push('迁移脚本检查');
    return c;
  };
  O.formName = (id) => (RAW[id] ? RAW[id].name : '（已不在发布里）');
  O.releaseDeptName = (id) => { const d = RAW.three.depts.find((x) => x.id === id); return d ? d.name : null; };

  // ------------------------------------------------------------------ 合成

  const LIST_FIELDS = ['watches', 'produces', 'tools'];
  const SCALAR_FIELDS = ['name', 'goal', 'judge', 'how', 'who', 'write', 'verifies', 'completes'];
  const applyList = (base, c) => {
    if (Array.isArray(c)) return c.slice();
    return uniq(base.filter((x) => !((c && c.remove) || []).includes(x)).concat((c && c.add) || []));
  };

  function composeDept(fd, c, src) {
    const d = clone(fd);
    d.src = src; d.fieldSrc = {}; d.listSrc = {}; d.removedItems = {};
    delete d.added;
    if (src !== 'added' && c) {
      SCALAR_FIELDS.forEach((k) => { if (c[k] !== undefined) { d[k] = clone(c[k]); d.fieldSrc[k] = 'changed'; } });
      LIST_FIELDS.forEach((k) => {
        if (!c[k]) return;
        d[k] = applyList(fd[k], c[k]);
        d.fieldSrc[k] = 'changed'; d.listSrc[k] = {};
        ((c[k] && c[k].add) || []).forEach((x) => { if (!fd[k].includes(x)) d.listSrc[k][x] = 'added'; });
        d.removedItems[k] = ((c[k] && c[k].remove) || []).filter((x) => fd[k].includes(x));
      });
      if (Object.keys(d.fieldSrc).length) d.src = 'changed';
    }
    if (!d.roles || !d.roles.length) d.roles = [d.name + '角色'];
    return d;
  }
  const blankDept = (id) => D({ id, name: '', goal: '', judge: '', how: '', watches: [], produces: [], write: 'none', tools: [] });

  O.compose = function compose(spec, depth) {
    depth = depth || 0;
    const form = O.form(spec.form);
    const ch = spec.changes || {};
    const out = { form: spec.form, formName: O.formName(spec.form), missingForm: !form, depth, rotation: 'by_outcome', rotationSrc: 'follow', adopt: '', adoptSrc: 'follow', unit: '', unitSrc: 'follow',
      outcomes: [], removedOutcomes: [], depts: [], removedDepts: [], sources: [], observers: [], unknown: (ch._unknown || []).slice(), orphans: 0 };
    if (!form) return out;
    ['rotation', 'adopt', 'unit'].forEach((k) => { out[k] = ch[k] !== undefined ? ch[k] : form[k]; out[k + 'Src'] = ch[k] !== undefined ? 'changed' : 'follow'; });
    if (!O.ROTATIONS[out.rotation]) out.unknown.push('这个发布没有轮转方式「' + out.rotation + '」');

    const oc = ch.outcomes || {};
    form.outcomes.forEach((o) => {
      const c = oc[o.id];
      if (c && c.removed) { out.removedOutcomes.push(Object.assign({}, o, { src: 'removed' })); return; }
      const item = Object.assign({}, o, { src: 'follow', fieldSrc: {} });
      if (c) Object.keys(c).forEach((k) => { if (k !== 'added' && k !== 'removed') { item[k] = c[k]; item.fieldSrc[k] = 'changed'; item.src = 'changed'; } });
      out.outcomes.push(item);
    });
    Object.keys(oc).forEach((id) => {
      if (oc[id].added) out.outcomes.push(Object.assign({ id, name: '', desc: '', basedOn: 'input', receipt: false, snapshot: false }, clone(oc[id]), { src: 'added', fieldSrc: {} }));
      else if (!form.outcomes.some((o) => o.id === id)) out.orphans += 1;
    });

    const dc = ch.depts || {};
    form.depts.forEach((fd) => {
      const c = dc[fd.id];
      if (c && c.removed) { out.removedDepts.push(Object.assign(composeDept(fd, c, 'follow'), { src: 'removed' })); return; }
      out.depts.push(composeDept(fd, c, 'follow'));
    });
    Object.keys(dc).forEach((id) => {
      if (dc[id].added) out.depts.push(composeDept(Object.assign(blankDept(id), clone(dc[id])), null, 'added'));
      else if (!form.depts.some((d) => d.id === id)) out.orphans += 1;
    });

    const sc = ch.sources || {};
    (form.sources || []).forEach((s) => out.sources.push({ id: s.id, name: s.name, to: sc[s.id] !== undefined ? sc[s.id] : s.to, src: sc[s.id] !== undefined ? 'changed' : 'follow' }));
    Object.keys(sc).forEach((id) => { if (!(form.sources || []).some((s) => s.id === id)) out.orphans += 1; });
    out.depts.concat(out.removedDepts).forEach((d) => { d.receives = out.sources.filter((s) => s.to === d.id); });

    const obc = ch.observers || {};
    (form.observers || []).forEach((ob) => {
      const c = obc[ob.id];
      const o = Object.assign({}, ob, { src: c ? 'changed' : 'follow' });
      if (c) { if (c.on !== undefined) o.on = c.on; if (c.scope !== undefined) o.scope = c.scope; }
      out.observers.push(o);
    });

    const tools = O.toolNames();
    out.depts.forEach((d) => {
      d.tools.forEach((t) => { if (!tools.includes(t)) out.unknown.push('「' + d.name + '」的工具许可里有「' + t + '」，这个发布没有这个工具'); });
      if (!O.WRITE[d.write]) out.unknown.push('「' + d.name + '」的写入范围「' + d.write + '」不认识');
      if (!O.WHO[(d.who || {}).type]) out.unknown.push('「' + d.name + '」的「由谁做」不认识');
      if (d.who && d.who.type === 'suborg') {
        if (depth + 1 > O.MAX_DEPTH) d.subTooDeep = true;
        else d.sub = compose({ form: d.who.form, changes: d.who.changes || {} }, depth + 1);
      }
    });
    return out;
  };

  O.nodeAt = (root, path) => path.reduce((c, id) => { const d = c && c.depts.find((x) => x.id === id); return d && d.sub ? d.sub : null; }, root);

  const kindName = (c, id) => { if (id === 'input') return c.depth > 0 ? '上一层交来的任务' : '你的输入'; const o = c.outcomes.find((x) => x.id === id) || c.removedOutcomes.find((x) => x.id === id); return o ? o.name : '（不存在的成果）'; };
  O.kindName = kindName;
  const live = (c) => c.depts;
  const byId = (c, id) => c.depts.find((d) => d.id === id);

  // ------------------------------------------------------------------ 摘要版本

  function hash(str) {
    let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (let i = 0; i < str.length; i++) { const ch = str.charCodeAt(i); h1 = Math.imul(h1 ^ ch, 2654435761); h2 = Math.imul(h2 ^ ch, 1597334677); }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return ((h1 >>> 0).toString(16).padStart(8, '0') + (h2 >>> 0).toString(16).padStart(8, '0')).slice(0, 6);
  }
  // 冻结进事项的部分：不含观察者
  O.core = (c) => ({ s: c.sources.map((s) => [s.id, s.to]), r: c.rotation, a: c.adopt, u: c.unit, o: c.outcomes.map((o) => [o.id, o.name, o.desc, o.basedOn, o.receipt, o.snapshot]),
    d: c.depts.map((d) => [d.id, d.name, d.goal, d.judge, d.how, d.watches, d.produces, d.verifies, d.completes, d.write, d.tools, (d.who || {}).type, (d.who || {}).agent || '', d.sub ? O.core(d.sub) : null]) });
  O.coreDigest = (c) => hash(JSON.stringify(O.core(c)));
  O.version = (c) => hash(JSON.stringify([O.core(c), c.observers.map((o) => [o.id, o.on, o.scope])]));

  // ------------------------------------------------------------------ 结束方式、成果怎么走

  O.completer = (c) => live(c).find((d) => d.completes) || null;
  // 事项最后采纳的成果：按成果是 adopt；直做是交完成的那个角色交出的成果
  const adoptKind = (c) => { if (c.rotation !== 'direct') return c.adopt; const d = O.completer(c); return d && d.produces[0] ? d.produces[0] : ''; };
  O.verifiers = (c) => {
    const k = adoptKind(c), cp = c.rotation === 'direct' ? O.completer(c) : null;
    return live(c).filter((v) => v.verifies && v.verifies.kind === k && byId(c, v.verifies.dept) && (c.rotation !== 'direct' || (cp && v.verifies.dept === cp.id)));
  };
  const isOut = (d) => d.who && d.who.type === 'outsourced';
  const label = (d) => d.name + (isOut(d) ? '（外包）' : '');
  const verWho = (vs) => (vs.length > 1 ? '每个核验角色（' + vs.map((v) => v.name).join('、') + '）都放行' : vs[0].name + '放行');

  O.ending = function ending(c) {
    const up = c.depth > 0 ? '；完成后结果作为提案回到上一层' : '';
    if (c.missingForm) return { text: '形态已经不在发布里，没法判断事项怎么结束', open: true, outsourced: false };
    if (c.rotation === 'direct') {
      const d = O.completer(c);
      if (!d) return { text: '还没有指定谁交完成，事项没法结束', open: true, outsourced: false };
      const vs = O.verifiers(c);
      if (vs.length) return { text: d.name + '交完成以后等' + (vs.length > 1 ? '每个核验角色（' + vs.map((v) => v.name).join('、') + '）都' : vs[0].name) + '放行，打回则' + d.name + '再做一轮' + up, open: false, outsourced: false };
      return isOut(d)
        ? { text: d.name + '（外包）交回快照就结束，记为开环完成并注明外包' + up, open: true, outsourced: true }
        : { text: d.name + '交完成就结束，记为开环完成' + up, open: true, outsourced: false };
    }
    const ads = live(c).filter((d) => d.produces.includes(c.adopt));
    if (!c.adopt || !ads.length) return { text: '还没有写明事项最后采纳哪种成果，或者没有部门交出它，事项没法结束', open: true, outsourced: false };
    const vs = O.verifiers(c);
    const out = ads.some(isOut);
    if (!vs.length) return { text: '交了完成就结束，记为开环完成' + (out ? '，注明外包' : '') + up, open: true, outsourced: out };
    const target = byId(c, vs[0].verifies.dept);
    return { text: verWho(vs) + '才算完成，打回时' + target.name + '返工' + up, open: false, outsourced: false };
  };

  // 事项的来源 → 接它的部门
  O.sourceReceiver = (c, id) => { const s = c.sources.find((x) => x.id === id); return s ? byId(c, s.to) || null : null; };
  O.firstReceivers = (c) => { const s = c.sources.find((x) => x.id === 'input' || x.id === 'task'); const d = s && byId(c, s.to); return d ? [d] : []; };
  // 每个接着来源的部门：{ to, dept, names }，按来源出现的顺序
  O.sourceGroups = (c) => {
    const g = [];
    c.sources.forEach((s) => {
      let e = g.find((x) => x.to === s.to);
      if (!e) { e = { to: s.to, dept: byId(c, s.to) || null, names: [] }; g.push(e); }
      e.names.push(s.name);
    });
    return g;
  };

  // 成果怎么走：分成三类，小图与文字用同一份
  O.flowParts = function flowParts(c) {
    const src = [], out = [], ver = [], asks = [];
    const vs = O.verifiers(c);
    const open = O.ending(c).open;
    const endVerified = c.depth > 0 ? '结果作为提案回到上一层' : '事项完成';
    const endOpen = c.depth > 0 ? '开环完成，结果作为提案回到上一层' : '开环完成';
    const direct = c.rotation === 'direct';
    const grp = O.sourceGroups(c);
    live(c).forEach((d) => {
      const g = grp.find((x) => x.to === d.id);
      const pre = g ? g.names.join('、') + ' → ' : '';
      let first = true;
      uniq(d.produces).filter((k) => c.outcomes.some((o) => o.id === k)).forEach((k) => {
        const ws = live(c).filter((w) => w.id !== d.id && w.watches.includes(k)).map(label);
        let tail = ws.join('、');
        if (direct && d.completes) { if (open) tail = tail ? tail + ' → ' + endOpen : endOpen; }
        else if (k === c.adopt && open) tail = tail ? tail + ' → ' + endOpen : endOpen;
        if (!tail) tail = '成果库';
        const line = label(d) + ' → ' + kindName(c, k) + ' → ' + tail;
        if (direct) out.push((first ? pre : '') + line); else { if (first && pre) src.push(pre + label(d)); out.push(line); }
        first = false;
      });
      if (first && pre) src.push(pre + label(d));
      if (direct && !d.produces.length && !d.verifies) { const cp = O.completer(c); if (cp && cp.id !== d.id) asks.push(cp.name + ' → 询问 → ' + d.name + ' → 回答 → ' + cp.name); }
      if (vs.includes(d)) ver.push(label(d) + ' → 放行 → ' + endVerified);
    });
    return { src, out: out.concat(asks), ver };
  };
  O.flow = (c) => { const f = O.flowParts(c); return f.src.concat(f.out, f.ver); };

  // 四个问题的回答：事项从哪来、谁做、谁核验、怎么结束；组织页头部、目录卡、新建项目的下拉都用它
  O.answers = function answers(c) {
    const ds = live(c);
    const tag = (d) => d.name + (isOut(d) ? '（外包）' : '') + (d.who && d.who.type === 'suborg' ? '（内部是子组织）' : '');
    const from = O.sourceGroups(c).map((g) => g.names.join('、') + ' → ' + (g.dept ? tag(g.dept) : '没有部门接')).join('；');
    let who;
    if (ds.length === 1) {
      const d = ds[0];
      who = d.who && d.who.type === 'outsourced' ? '一个外包角色「' + d.name + '」，外部 agent：' + (d.who.agent || '未选')
        : d.who && d.who.type === 'suborg' ? '「' + d.name + '」，内部是子组织' : '一个自有角色「' + d.name + '」';
    } else if (c.rotation === 'direct') {
      const cp = O.completer(c);
      who = ds.map(tag).join('、') + (ds.every((d) => !d.who || d.who.type === 'own') ? '，' + ds.length + ' 个自有角色' : '') + '，靠询问交流' + (cp ? '，' + cp.name + '交完成' : '');
    } else who = ds.map(tag).join('、') + '，' + (c.rotation === 'by_outcome' ? '按成果轮转' : O.ROTATIONS[c.rotation]);
    const vs = ds.filter((d) => d.verifies);
    const verify = vs.length ? vs.map((v) => v.name + '核验' + ((byId(c, v.verifies.dept) || {}).name || '？') + (c.rotation === 'direct' ? '交的完成' : '的' + kindName(c, v.verifies.kind))).join('；') : '没有核验角色';
    return { from, who, verify, end: O.ending(c).text };
  };

  // 目录：五份形态、两个层。前四份的回答从形态数据算出来；三部门加运维只有卡上的文字
  O.CATALOG = function catalog() {
    const forms = O.PUBLISHED.map((id) => { const c = O.compose({ form: id, changes: {} }); return { id, name: O.formName(id), note: O.form(id).note, tip: O.form(id).tip, a: O.answers(c), selectable: true }; });
    forms.push({ id: 'three_ops', name: '三部门加运维', note: '三部门之外多一种事项的来源「运维发现的故障」', stage: '发布带还没有', selectable: false,
      a: { from: '你的输入、建档 → 产品；多一种来源「运维发现的故障」', who: '发布带还没有', verify: '发布带还没有', end: '发布带还没有' } });
    const hub = O.answers(O.compose({ form: 'hub', changes: {} }));
    const layers = [
      { id: 'observer', name: '观察者', note: '能叠在任何一份形态上；在组织页的「观察者」一块开关', a: { from: '不开事项，在事项外面读事实', who: '不做事，产出证据、提案、振荡信号', verify: '不核验，也不能核验', end: '不改事项怎么结束' } },
      { id: 'suborg', name: '部门内子组织', note: '能叠在任何自有角色上；某个角色的「由谁做」选子组织，在部门详情里选', a: { from: hub.from, who: hub.who, verify: hub.verify + '（子组织里自己定）', end: '子事项的结果作为这个角色的提案回到上一层' } }
    ];
    return { forms, layers };
  };

  // 发布的部门（三部门里的）放进别的形态时的样子：直做形态里关注交完成，默认核验交完成的角色
  O.releaseDepts = (c) => RAW.three.depts.filter((d) => c.depth === 0 && !c.depts.some((x) => x.id === d.id) && !c.removedDepts.some((x) => x.id === d.id)).map((d) => d.id);
  O.publishedDept = function publishedDept(c, id) {
    const d = clone(RAW.three.depts.find((x) => x.id === id));
    if (c.rotation === 'direct') {
      const cp = O.completer(c), kinds = cp ? cp.produces : [];
      d.watches = kinds.slice(); d.produces = [];
      d.verifies = d.verifies && cp && kinds[0] ? { dept: cp.id, kind: kinds[0] } : null;
    }
    return d;
  };

  // ------------------------------------------------------------------ 结构校验

  // ctx: { modelOf(dept, depth), items: 还没有结束的事项 }
  function check(c, prefix, ctx, R, W, ids) {
    const rej = (rule, text, extra) => R.push(Object.assign({ rule, text: prefix + text }, extra || {}));
    const warn = (rule, text) => W.push({ rule, text: prefix + text });
    if (c.missingForm) { rej(10, '这个形态已经不在发布里'); return; }
    const ds = live(c);
    // 1 谁能拒绝谁有环，含核验自己
    const edge = {};
    ds.forEach((v) => { if (v.verifies && byId(c, v.verifies.dept)) edge[v.id] = v.verifies.dept; });
    const reported = [];
    ds.forEach((v) => {
      if (reported.includes(v.id)) return;
      if (edge[v.id] === v.id) { reported.push(v.id); rej(1, '「' + v.name + '」核验自己'); return; }
      const seen = [v.id]; let cur = edge[v.id];
      while (cur && !seen.includes(cur)) { seen.push(cur); cur = edge[cur]; }
      if (cur === v.id) { seen.forEach((id) => reported.push(id)); rej(1, '「' + v.name + '」核验的链条绕回了自己：' + seen.map((id) => byId(c, id).name).join(' → ') + ' → ' + v.name); }
    });
    // 2 核验对象不存在
    ds.forEach((v) => {
      if (!v.verifies) return;
      const t = byId(c, v.verifies.dept);
      if (!t) rej(2, '「' + v.name + '」要核验的部门已经不存在');
      else if (!t.produces.includes(v.verifies.kind)) rej(2, '「' + v.name + '」要核验「' + t.name + '」的「' + kindName(c, v.verifies.kind) + '」，但「' + t.name + '」不交出这种成果');
    });
    // 3 有一种事项的来源没有部门接
    c.sources.forEach((s) => {
      if (byId(c, s.to)) return;
      const gone = (c.removedDepts.find((x) => x.id === s.to) || {}).name || O.releaseDeptName(s.to) || s.to;
      rej(3, '有一种事项的来源没有部门接：「' + s.name + '」。原来接它的「' + gone + '」不在这份组织里，这种事项开始不了；请改给' + (ds.length ? ds.map((d) => '「' + d.name + '」').join('、') + '里的一个接' : '某个部门接'),
        { source: s.id, sourceName: s.name, options: ds.map((d) => ({ id: d.id, name: d.name })) });
    });
    // 4 关注的成果没有部门交
    ds.forEach((d) => d.watches.forEach((k) => {
      if (O.BUILTIN[k]) return;
      if (!ds.some((x) => x.produces.includes(k))) rej(4, '「' + d.name + '」关注「' + kindName(c, k) + '」，但没有部门交出它');
    }));
    // 5 事项无法结束
    if (c.rotation === 'direct') { if (!O.completer(c)) rej(5, '直做时没有指定谁交完成，事项没法结束'); }
    else if (!c.adopt || !c.outcomes.some((o) => o.id === c.adopt)) rej(5, '没有写明事项最后采纳哪种成果，事项没法结束');
    else if (!ds.some((d) => d.produces.includes(c.adopt))) rej(5, '事项最后采纳「' + kindName(c, c.adopt) + '」，但没有部门交出它，事项没法结束');
    // 6 核验角色外包
    ds.forEach((v) => { if (v.verifies && isOut(v)) rej(6, '「' + v.name + '」是核验角色，不能外包'); });
    // 7 运行工作区有两个写入者
    const writers = ds.filter((d) => d.write === 'workspace');
    if (writers.length > 1) rej(7, '运行工作区有 ' + writers.length + ' 个写入者：' + writers.map((d) => d.name).join('、') + '，只能有一个');
    // 8 新增的部门缺三样
    ds.filter((d) => d.src === 'added').forEach((d) => {
      const miss = [['goal', '它对什么负责'], ['judge', '凭什么判断'], ['how', '怎么工作']].filter((f) => !String(d[f[0]] || '').trim()).map((f) => '「' + f[1] + '」');
      if (miss.length) rej(8, '新增的「' + (d.name || '未命名的部门') + '」还缺' + miss.join('、'));
    });
    // 9 子组织超过深度上限
    ds.forEach((d) => { if (d.subTooDeep) rej(9, '「' + d.name + '」指向子组织，嵌套超过了上限（' + O.MAX_DEPTH + ' 层）'); });
    // 10 未知的字段、工具、轮转方式
    c.unknown.forEach((u) => rej(10, u));

    // 提醒
    const end = O.ending(c);
    const vsAll = ds.filter((d) => d.verifies);
    if (end.open && c.rotation !== 'direct' && !vsAll.length) warn(1, '事项最后采纳的成果没有核验角色核验，事项以开环完成结束' + (end.outsourced ? '（注明外包）' : ''));
    else if (end.open && c.rotation !== 'direct') warn(2, '核验角色' + vsAll.map((v) => '「' + v.name + '」').join('、') + '只核验中途的成果，事项最后采纳的成果没有人核验，同样以开环完成结束' + (end.outsourced ? '（注明外包）' : ''));
    else if (end.open && c.rotation === 'direct' && vsAll.length) warn(2, '核验角色' + vsAll.map((v) => '「' + v.name + '」').join('、') + '核验的不是交完成的那份成果，事项以开环完成结束')
    else if (end.open && c.rotation === 'direct' && c.depth === 0) warn(1, '这个组织没有核验角色，事项以开环完成结束' + (end.outsourced ? '（注明外包）' : ''));
    vsAll.forEach((v) => {
      const m = ctx.modelOf(v, c.depth, ids);
      if (m && O.MODELS[m] && !O.MODELS[m].vision) warn(3, '核验角色「' + v.name + '」的模型「' + m + '」不能看图像，依赖外观或桌面程序的验收条件无法核验；仍然可以采用');
    });
    ds.forEach((d) => { if (!ctx.modelOf(d, c.depth, ids)) warn(4, '「' + d.name + '」还没有可用的模型，新建事项会被拒绝'); });
    ds.forEach((d) => { if (!d.produces.length && !d.completes && !d.verifies) warn(5, '「' + d.name + '」不交出任何成果，只回答询问'); });
    if (c.depth === 0) {
      const core = O.coreDigest(c);
      const n = (ctx.items || []).filter((i) => i.org && i.org.core !== core).length;
      if (n) warn(6, '还有 ' + n + ' 个事项在按旧组织跑或在排队，采用以后它们不变');
    }
    ds.forEach((d) => { if (d.sub) check(d.sub, prefix + d.name + ' › 内部：', ctx, R, W, ids.concat(d.id)); });
  }

  O.validate = function validate(c, ctx) {
    const R = [], W = [];
    check(c, '', ctx || { modelOf: () => 'x', items: [] }, R, W, []);
    return { rejects: R, warns: W, ending: O.ending(c), flow: O.flow(c), notes: c.orphans ? ['有 ' + c.orphans + ' 项改动对应的对象已经不在发布里，没有起作用'] : [] };
  };
  O.REJECT_TITLES = { 1: '谁能拒绝谁有环', 2: '核验对象不存在', 3: '有一种事项的来源没有部门接', 4: '关注的成果没有部门交', 5: '事项无法结束', 6: '核验角色外包', 7: '运行工作区有两个写入者', 8: '新增的部门缺三样说明', 9: '子组织超过嵌套深度', 10: '未知的字段、工具或轮转方式' };

  // ------------------------------------------------------------------ 差异

  const whoText = (w) => (w.type === 'outsourced' ? '外包（' + (w.agent || '未选') + '）' : w.type === 'suborg' ? '子组织（' + O.formName(w.form) + '）' : '自有角色');
  const verText = (c, v) => (v ? '核验「' + ((byId(c, v.dept) || {}).name || '？') + '」的「' + kindName(c, v.kind) + '」' : '不核验');
  O.diff = function diff(a, b, prefix) {
    prefix = prefix || '';
    const L = [];
    const add = (t) => L.push(prefix + t);
    if (a.form !== b.form) add('形态：' + a.formName + ' → ' + b.formName);
    if (a.rotation !== b.rotation) add('轮转方式：' + (O.ROTATIONS[a.rotation] || a.rotation) + ' → ' + (O.ROTATIONS[b.rotation] || b.rotation));
    if (a.adopt !== b.adopt) add('事项最后采纳的成果：' + (kindName(a, a.adopt) || '无') + ' → ' + (kindName(b, b.adopt) || '无'));
    if (a.unit !== b.unit) add('工作单元的大小：' + (a.unit || '无') + ' → ' + (b.unit || '无'));
    b.sources.forEach((y) => {
      const x = a.sources.find((o) => o.id === y.id);
      if (x && x.to !== y.to) add('事项的来源「' + y.name + '」：由「' + (byId(a, x.to) || { name: '？' }).name + '」接 → 由「' + (byId(b, y.to) || { name: '？' }).name + '」接');
    });
    uniq(a.outcomes.map((o) => o.id).concat(b.outcomes.map((o) => o.id))).forEach((id) => {
      const x = a.outcomes.find((o) => o.id === id), y = b.outcomes.find((o) => o.id === id);
      if (!x) add('新增成果种类「' + y.name + '」');
      else if (!y) add('去掉成果种类「' + x.name + '」');
      else if (x.name !== y.name || x.desc !== y.desc || x.basedOn !== y.basedOn || x.receipt !== y.receipt || x.snapshot !== y.snapshot) add('成果种类「' + y.name + '」有改动');
    });
    uniq(a.depts.map((d) => d.id).concat(b.depts.map((d) => d.id))).forEach((id) => {
      const x = byId(a, id), y = byId(b, id);
      if (!x) { add('新增部门「' + y.name + '」'); return; }
      if (!y) { add('去掉部门「' + x.name + '」'); return; }
      if (x.name !== y.name) add('「' + x.name + '」改名为「' + y.name + '」');
      [['goal', '它对什么负责'], ['judge', '凭什么判断'], ['how', '怎么工作']].forEach((f) => { if (x[f[0]] !== y[f[0]]) add('「' + y.name + '」的「' + f[1] + '」有改动'); });
      [['tools', '工具许可', (k) => k], ['watches', '关注的成果', (k) => kindName(b, k)], ['produces', '交出的成果', (k) => kindName(b, k)]].forEach((f) => {
        const ad = y[f[0]].filter((k) => !x[f[0]].includes(k)), rm = x[f[0]].filter((k) => !y[f[0]].includes(k));
        if (ad.length) add('「' + y.name + '」的' + f[1] + '增加：' + ad.map(f[2]).join('、'));
        if (rm.length) add('「' + y.name + '」的' + f[1] + '去掉：' + rm.map((k) => (f[0] === 'tools' ? k : kindName(a, k))).join('、'));
      });
      if (!same([x.who.type, x.who.agent, x.who.form], [y.who.type, y.who.agent, y.who.form])) add('「' + y.name + '」由谁做：' + whoText(x.who) + ' → ' + whoText(y.who));
      if (x.write !== y.write) add('「' + y.name + '」的写入范围：' + O.WRITE[x.write] + ' → ' + O.WRITE[y.write]);
      if (!same(x.verifies, y.verifies)) add('「' + y.name + '」的核验声明：' + verText(a, x.verifies) + ' → ' + verText(b, y.verifies));
      if (x.completes !== y.completes) add('「' + y.name + '」' + (y.completes ? '改为交完成' : '不再交完成'));
      if (x.sub && y.sub) O.diff(x.sub, y.sub, prefix + y.name + ' › 内部：').forEach((t) => L.push(t));
      else if (!x.sub && y.sub) add('「' + y.name + '」的子组织：' + y.sub.formName);
    });
    b.observers.forEach((ob) => {
      const x = a.observers.find((o) => o.id === ob.id);
      if (!x) add('观察者「' + ob.name + '」' + (ob.on ? '开' : '关'));
      else {
        if (x.on !== ob.on) add('观察者「' + ob.name + '」：' + (x.on ? '开' : '关') + ' → ' + (ob.on ? '开' : '关'));
        if (x.scope !== ob.scope) add('观察者「' + ob.name + '」的读取范围：' + x.scope + ' → ' + ob.scope);
      }
    });
    return L;
  };

  O.count = function count(ch) {
    if (!ch) return 0;
    let n = ['rotation', 'adopt', 'unit'].filter((k) => ch[k] !== undefined).length + Object.keys(ch.sources || {}).length;
    ['depts', 'outcomes', 'observers'].forEach((k) => {
      Object.keys(ch[k] || {}).forEach((id) => {
        n += 1;
        const e = ch[k][id];
        if (e && e.who && e.who.changes) n += O.count(e.who.changes);
      });
    });
    return n;
  };

  // ------------------------------------------------------------------ 改动的读写（草稿用）

  // 取得某一层（路径）的形态与改动对象；中途缺的 who 从形态复制出来，好往里写
  O.changesAt = function changesAt(rootChanges, rootForm, path) {
    let ch = rootChanges, fid = rootForm;
    path.forEach((id) => {
      ch.depts = ch.depts || {};
      const e = ch.depts[id] = ch.depts[id] || {};
      if (!e.who) { const fd = O.form(fid).depts.find((d) => d.id === id); e.who = clone(fd.who); }
      e.who.changes = e.who.changes || {};
      ch = e.who.changes; fid = e.who.form;
    });
    return { changes: ch, form: O.form(fid) };
  };

  // 写一项；和形态一样的就不记（回到「跟随发布」）。value 对清单类给最终的整张清单
  O.setField = function setField(rootChanges, rootForm, path, coll, id, field, value) {
    const at = O.changesAt(rootChanges, rootForm, path);
    const ch = at.changes;
    ch[coll] = ch[coll] || {};
    const e = ch[coll][id] = ch[coll][id] || {};
    const baseColl = coll === 'depts' ? at.form.depts : coll === 'outcomes' ? at.form.outcomes : at.form.observers;
    const base = baseColl.find((x) => x.id === id);
    if (e.added || !base) { e[field] = clone(value); return; }
    if (LIST_FIELDS.includes(field)) {
      const add = value.filter((x) => !base[field].includes(x)), remove = base[field].filter((x) => !value.includes(x));
      if (add.length || remove.length) e[field] = { add, remove }; else delete e[field];
    } else if (same(value, base[field])) delete e[field];
    else e[field] = clone(value);
    if (!Object.keys(e).length) delete ch[coll][id];
  };
  O.restoreField = (rootChanges, rootForm, path, coll, id, field) => {
    const at = O.changesAt(rootChanges, rootForm, path);
    const e = (at.changes[coll] || {})[id];
    if (e) { delete e[field]; if (!Object.keys(e).length) delete at.changes[coll][id]; }
  };
  // 改某一种来源由哪个部门接（单值，整项替换）；和形态一样的就不记
  O.setSource = (rootChanges, rootForm, path, id, deptId) => {
    const at = O.changesAt(rootChanges, rootForm, path);
    const base = (at.form.sources || []).find((s) => s.id === id);
    at.changes.sources = at.changes.sources || {};
    if (base && base.to === deptId) delete at.changes.sources[id]; else at.changes.sources[id] = deptId;
    if (!Object.keys(at.changes.sources).length) delete at.changes.sources;
  };
  O.setTop = (rootChanges, rootForm, path, key, value) => {
    const at = O.changesAt(rootChanges, rootForm, path);
    const base = at.form[key];
    if (same(value, base)) delete at.changes[key]; else at.changes[key] = value;
  };

  // 去掉一个部门：连带去掉别的部门对它独占交出的成果的关注（否则会被「没有部门交」拒绝）；恢复时反着做
  O.removeDept = function removeDept(rootChanges, rootForm, path, id) {
    const at = O.changesAt(rootChanges, rootForm, path);
    const fd = at.form.depts.find((d) => d.id === id);
    if (!fd) { (at.changes.depts || {})[id] = null; delete (at.changes.depts || {})[id]; return; }
    const e = (at.changes.depts = at.changes.depts || {})[id] = at.changes.depts[id] || {};
    e.removed = true;
    const comp = O.compose({ form: at.form.id, changes: at.changes });
    fd.produces.forEach((k) => {
      if (comp.depts.some((d) => d.produces.includes(k))) return;
      comp.depts.forEach((d) => { if (d.watches.includes(k) && !(at.form.depts.find((x) => x.id === d.id) || {}).added) O.setField(rootChanges, rootForm, path, 'depts', d.id, 'watches', d.watches.filter((w) => w !== k)); });
    });
  };
  O.restoreDept = function restoreDept(rootChanges, rootForm, path, id) {
    const at = O.changesAt(rootChanges, rootForm, path);
    const fd = at.form.depts.find((d) => d.id === id);
    if (!at.changes.depts || !at.changes.depts[id]) return;
    delete at.changes.depts[id].removed;
    if (!Object.keys(at.changes.depts[id]).length) delete at.changes.depts[id];
    if (!fd) return;
    // 把别的部门因为它被去掉的关注补回来
    at.form.depts.forEach((d) => {
      if (d.id === id) return;
      const e = (at.changes.depts || {})[d.id];
      if (e && e.watches && e.watches.remove) {
        const back = e.watches.remove.filter((k) => fd.produces.includes(k));
        if (back.length) {
          e.watches.remove = e.watches.remove.filter((k) => !back.includes(k));
          if (!e.watches.remove.length && !(e.watches.add || []).length) delete e.watches;
          if (!Object.keys(e).length) delete at.changes.depts[d.id];
        }
      }
    });
  };

  // ------------------------------------------------------------------ 文档视图：本项目的改动 <-> 带中文字段名的文本

  const F = {
    top: { sources: '事项的来源', rotation: '轮转方式', adopt: '事项最后采纳的成果', unit: '工作单元的大小', depts: '部门', outcomes: '成果种类', observers: '观察者' },
    dept: { removed: '去掉', added: '新增', name: '显示名', goal: '对什么负责', judge: '凭什么判断', how: '怎么工作', who: '由谁做', write: '写入范围', verifies: '核验', completes: '交完成', watches: '关注的成果', produces: '交出的成果', tools: '工具许可' },
    outcome: { removed: '去掉', added: '新增', name: '显示名', desc: '说明', basedOn: '依据', receipt: '带检查回执', snapshot: '带代码快照' },
    observer: { on: '开关', scope: '读取范围' },
    who: { type: '方式', agent: '外部 agent', form: '形态', changes: '改动' },
    ver: { dept: '部门', kind: '成果' }
  };
  const inv = (o) => Object.keys(o).reduce((m, k) => { m[o[k]] = k; return m; }, {});
  const rev = (m, v) => { const r = inv(m)[v]; return r === undefined ? v : r; };
  const addedLabel = (coll, id) => (coll === 'depts' ? '新增部门' : '新增成果') + id.slice(1);

  function idLabel(form, coll, id) {
    const list = coll === 'depts' ? form.depts : form.outcomes;
    const f = list.find((x) => x.id === id);
    if (f) return f.name;
    if (coll === 'depts' && O.releaseDeptName(id)) return O.releaseDeptName(id);
    return addedLabel(coll, id);
  }
  function labelId(form, coll, lab, ch) {
    const list = coll === 'depts' ? form.depts : form.outcomes;
    const f = list.find((x) => x.name === lab);
    if (f) return f.id;
    if (coll === 'depts') { const r = RAW.three.depts.find((d) => d.name === lab); if (r) return r.id; }
    const m = /^新增(部门|成果)(\d+)$/.exec(lab);
    if (m) return (m[1] === '部门' ? 'n' : 'k') + m[2];
    return null;
  }

  O.toDoc = function toDoc(ch, form) {
    ch = ch || {};
    const d = {};
    ['rotation', 'adopt', 'unit'].forEach((k) => {
      if (ch[k] === undefined) return;
      d[F.top[k]] = k === 'rotation' ? (O.ROTATIONS[ch[k]] || ch[k]) : k === 'adopt' ? idLabel(form, 'outcomes', ch[k]) : ch[k];
    });
    const so = {};
    Object.keys(ch.sources || {}).forEach((id) => { const s = (form.sources || []).find((x) => x.id === id); so[s ? s.name : id] = idLabel(form, 'depts', ch.sources[id]); });
    if (Object.keys(so).length) d[F.top.sources] = so;
    const dd = {};
    Object.keys(ch.depts || {}).forEach((id) => {
      const e = ch.depts[id], x = {};
      Object.keys(e).forEach((k) => {
        const v = e[k], key = F.dept[k];
        if (!key) return;
        if (k === 'removed' || k === 'added' || k === 'completes') x[key] = v;
        else if (k === 'write') x[key] = O.WRITE[v] || v;
        else if (k === 'verifies') x[key] = v ? { [F.ver.dept]: idLabel(form, 'depts', v.dept), [F.ver.kind]: idLabel(form, 'outcomes', v.kind) } : null;
        else if (k === 'who') {
          const w = { [F.who.type]: O.WHO[v.type] || v.type };
          if (v.agent) w[F.who.agent] = v.agent;
          if (v.form) { w[F.who.form] = O.formName(v.form); if (v.changes && Object.keys(v.changes).length) w[F.who.changes] = O.toDoc(v.changes, O.form(v.form) || { depts: [], outcomes: [] }); }
          x[key] = w;
        } else if (LIST_FIELDS.includes(k)) {
          const conv = (arr) => (k === 'tools' ? arr : arr.map((i) => idLabel(form, 'outcomes', i)));
          x[key] = Array.isArray(v) ? conv(v) : { 增加: conv(v.add || []), 去掉: conv(v.remove || []) };
        } else x[key] = v;
      });
      dd[idLabel(form, 'depts', id)] = x;
    });
    if (Object.keys(dd).length || !Object.keys(d).length) d[F.top.depts] = dd;
    const oo = {};
    Object.keys(ch.outcomes || {}).forEach((id) => {
      const e = ch.outcomes[id], x = {};
      Object.keys(e).forEach((k) => { if (F.outcome[k]) x[F.outcome[k]] = k === 'basedOn' ? idLabel(form, 'outcomes', e[k]) : e[k]; });
      oo[idLabel(form, 'outcomes', id)] = x;
    });
    d[F.top.outcomes] = oo;
    const ob = {};
    Object.keys(ch.observers || {}).forEach((id) => {
      const e = ch.observers[id], x = {};
      if (e.on !== undefined) x[F.observer.on] = e.on ? '开' : '关';
      if (e.scope !== undefined) x[F.observer.scope] = e.scope;
      ob[(O.OBSERVERS[id] || {}).name || id] = x;
    });
    d[F.top.observers] = ob;
    return d;
  };

  // 反过来：返回 { changes, unknown }；认不出的字段记在 unknown 里（会被「未知的字段」拒绝）
  O.fromDoc = function fromDoc(doc, form) {
    const ch = {}, unknown = [];
    const bad = (path, key) => unknown.push('未知的字段「' + key + '」' + (path ? '（在「' + path + '」里）' : ''));
    const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
    if (!isObj(doc)) { unknown.push('整份文档应该是一个对象'); return { changes: ch, unknown }; }
    Object.keys(doc).forEach((key) => {
      const k = rev(F.top, key), v = doc[key];
      if (!F.top[k]) { bad('', key); return; }
      if (k === 'rotation') ch.rotation = rev(O.ROTATIONS, v);
      else if (k === 'adopt') { const id = labelId(form, 'outcomes', v); ch.adopt = id || String(v); }
      else if (k === 'unit') ch.unit = v;
      else if (k === 'sources' && isObj(v)) {
        ch.sources = {};
        Object.keys(v).forEach((lab) => {
          const s = (form.sources || []).find((x) => x.name === lab), id = labelId(form, 'depts', v[lab]);
          if (!s) unknown.push('未知的事项的来源「' + lab + '」，来源的种类由发布给出，不能新增或去掉');
          else ch.sources[s.id] = id || String(v[lab]);
        });
      }
      else if (k === 'depts' && isObj(v)) {
        ch.depts = {};
        Object.keys(v).forEach((lab) => {
          const id = labelId(form, 'depts', lab);
          if (!id || !isObj(v[lab])) { unknown.push('未知的部门「' + lab + '」'); return; }
          const e = ch.depts[id] = {};
          Object.keys(v[lab]).forEach((fk) => {
            const k2 = rev(F.dept, fk), val = v[lab][fk];
            if (!F.dept[k2]) { bad(lab, fk); return; }
            if (k2 === 'write') e.write = rev(O.WRITE, val);
            else if (k2 === 'verifies') {
              if (val === null) e.verifies = null;
              else if (isObj(val)) {
                const dd = labelId(form, 'depts', val[F.ver.dept]), kk = labelId(form, 'outcomes', val[F.ver.kind]);
                e.verifies = { dept: dd || '?', kind: kk || '?' };
                Object.keys(val).forEach((x) => { if (x !== F.ver.dept && x !== F.ver.kind) bad(lab + ' › 核验', x); });
              } else bad(lab, fk);
            } else if (k2 === 'who' && isObj(val)) {
              const w = { type: rev(O.WHO, val[F.who.type]) };
              if (val[F.who.agent] !== undefined) w.agent = val[F.who.agent];
              if (val[F.who.form] !== undefined) { w.form = Object.keys(RAW).find((id) => RAW[id].name === val[F.who.form]) || '?'; }
              if (val[F.who.changes] !== undefined) {
                const sub = O.fromDoc(val[F.who.changes], O.form(w.form) || { depts: [], outcomes: [] });
                w.changes = sub.changes; if (sub.unknown.length) w.changes._unknown = sub.unknown.map((u) => lab + ' › ' + u);
              }
              Object.keys(val).forEach((x) => { if (!inv(F.who)[x] && !Object.values(F.who).includes(x)) bad(lab + ' › 由谁做', x); });
              e.who = w;
            } else if (LIST_FIELDS.includes(k2)) {
              const conv = (arr) => (k2 === 'tools' ? arr : arr.map((l) => labelId(form, 'outcomes', l) || '?'));
              if (Array.isArray(val)) e[k2] = conv(val);
              else if (isObj(val)) { e[k2] = { add: conv(val.增加 || []), remove: conv(val.去掉 || []) }; Object.keys(val).forEach((x) => { if (x !== '增加' && x !== '去掉') bad(lab + ' › ' + fk, x); }); }
              else bad(lab, fk);
            } else e[k2] = val;
          });
        });
      } else if (k === 'outcomes' && isObj(v)) {
        ch.outcomes = {};
        Object.keys(v).forEach((lab) => {
          const id = labelId(form, 'outcomes', lab);
          if (!id || !isObj(v[lab])) { unknown.push('未知的成果种类「' + lab + '」'); return; }
          const e = ch.outcomes[id] = {};
          Object.keys(v[lab]).forEach((fk) => {
            const k2 = rev(F.outcome, fk);
            if (!F.outcome[k2]) { bad(lab, fk); return; }
            e[k2] = k2 === 'basedOn' ? (labelId(form, 'outcomes', v[lab][fk]) || '?') : v[lab][fk];
          });
        });
      } else if (k === 'observers' && isObj(v)) {
        ch.observers = {};
        Object.keys(v).forEach((lab) => {
          const id = Object.keys(O.OBSERVERS).find((x) => O.OBSERVERS[x].name === lab);
          if (!id || !isObj(v[lab])) { unknown.push('未知的观察者「' + lab + '」'); return; }
          const e = ch.observers[id] = {};
          Object.keys(v[lab]).forEach((fk) => {
            const k2 = rev(F.observer, fk);
            if (!F.observer[k2]) { bad(lab, fk); return; }
            e[k2] = k2 === 'on' ? v[lab][fk] === '开' : v[lab][fk];
          });
        });
      } else bad('', key);
    });
    ['depts', 'outcomes', 'observers', 'sources'].forEach((k) => { if (ch[k] && !Object.keys(ch[k]).length) delete ch[k]; });
    if (unknown.length) ch._unknown = unknown;
    return { changes: ch, unknown };
  };

  // 合成结果的只读文档（右边那一栏）
  O.resultDoc = (c) => ({
    形态: c.formName, 事项的来源: c.sources.map((s) => s.name + ' → ' + ((byId(c, s.to) || {}).name || '没有部门接')), 轮转方式: O.ROTATIONS[c.rotation] || c.rotation, 事项最后采纳的成果: c.adopt ? kindName(c, c.adopt) : '无',
    部门: c.depts.map((d) => ({
      显示名: d.name, 来源: { follow: '跟随发布', changed: '本项目改过', added: '本项目加的' }[d.src], 对什么负责: d.goal, 凭什么判断: d.judge, 怎么工作: d.how,
      关注的成果: d.watches.map((k) => kindName(c, k)), 交出的成果: d.produces.map((k) => kindName(c, k)), 核验: d.verifies ? verText(c, d.verifies) : '不核验',
      由谁做: whoText(d.who), 写入范围: O.WRITE[d.write], 工具许可: d.tools
    })),
    成果种类: c.outcomes.map((o) => o.name),
    观察者: c.observers.map((o) => o.name + '：' + (o.on ? '开' : '关') + '，' + o.scope)
  });

  // ------------------------------------------------------------------ 项目上的组织

  const unfinished = (i) => !['adopted', 'open_closed', 'stopped'].includes(i.status);
  O.unfinished = unfinished;

  O.modelOf = function modelOf(p, id, pending) {
    const s = (pending && pending[id]) || (p.settings && p.settings.dept[id]);
    if (s && s.model) return s.model;
    const g = Y19.EXTRA && Y19.EXTRA.wiring[id];
    return g ? g.model : null;
  };
  // 子组织里的角色：本项目写了就用，没写入的跟随上一层的部门；ids 是上面各层部门的身份
  O.nodeModel = (p, ids, pending) => {
    if (ids.length === 1) return O.modelOf(p, ids[0], pending);
    const s = (p.settings.nodes || {})[ids.join('.')];
    return (s && s.model) || O.nodeModel(p, ids.slice(0, -1), pending);
  };
  O.ctxFor = (p, pending) => ({ modelOf: (d, depth, ids) => (depth > 0 ? O.nodeModel(p, (ids || []).concat(d.id), pending) : O.modelOf(p, d.id, pending)), items: p.items.filter(unfinished) });

  O.refresh = function refresh(p) {
    p.composed = O.compose({ form: p.org.form, changes: p.org.changes });
    p.version = O.version(p.composed);
    const liveIds = p.composed.depts.map((d) => d.id);
    const old = [];
    p.items.filter(unfinished).forEach((i) => { if (i.org) i.org.composed.depts.forEach((d) => { if (!liveIds.includes(d.id) && !old.includes(d.id)) old.push(d.id); }); });
    p.depts = liveIds.concat(old);
    p.onlyOld = old;
    p.depts.forEach((id) => { if (!p.deptState[id]) p.deptState[id] = O.idleState(p, id); });
  };
  O.idleState = (p, id) => {
    const d = p.composed.depts.find((x) => x.id === id) || { roles: [''] };
    return { text: '空闲', state: 'idle', reason: '手上没有事项', waits: [], role: d.roles[0], model: O.modelOf(p, id) || '未选', items: [] };
  };
  O.current = (p) => p.composed;
  O.status = function status(p) {
    const v = O.validate(p.composed, O.ctxFor(p));
    return { ok: !v.rejects.length, v };
  };
  O.summary = function summary(p) {
    const c = p.composed, e = O.ending(c);
    return { form: c.formName, changes: O.count(p.org.changes), rotation: O.ROTATIONS[c.rotation] || c.rotation, open: e.open, outsourced: e.outsourced, verifier: O.verifiers(c).map((v) => v.name), multi: c.depts.length > 1 };
  };
  // 精简页面（简洁的对话页）用的判断：直做、自有角色、一个做事角色（可加一个核验角色）、观察者全关、没有子组织。
  // 设计说明里外包也属于这一级，v19 只画个人博客，外包（logclean 这类）留到下一版，所以这里把外包排除在外。
  O.lean = (p) => {
    const c = p.composed;
    return c.rotation === 'direct' && c.depts.filter((d) => !d.verifies).length === 1 && c.depts.length <= 2 &&
      c.depts.every((d) => !d.who || d.who.type === 'own') && c.observers.every((o) => !o.on);
  };
  O.tags = (p) => {
    const s = O.summary(p);
    return [s.form + (s.changes ? '（改过 ' + s.changes + ' 处）' : ''), s.rotation, s.open ? '开环完成' + (s.outsourced ? '（外包）' : '') : '核验：' + s.verifier.join('、')];
  };
  // 部门的显示名：先看现在的组织，再看还在跑的事项冻结的，最后用发布里的名字
  O.deptName = function deptName(p, id) {
    if (!p || !p.composed) return O.releaseDeptName(id) || id;
    const d = byId(p.composed, id) || (p.composed.removedDepts || []).find((x) => x.id === id);
    if (d) return d.name;
    for (let n = 0; n < p.items.length; n++) { const f = p.items[n].org && p.items[n].org.composed.depts.find((x) => x.id === id); if (f) return f.name; }
    return O.releaseDeptName(id) || id;
  };
  // 数据里的 〔质检〕 写的是发布里的名字，按当前项目的组织换成现在的显示名
  O.token = function token(lab) {
    const id = RAW.three.depts.find((d) => d.name === lab);
    if (!id) return lab;
    const pid = Y19.h && Y19.h.ctxId();
    const p = pid && Y19.h.project(pid);
    return p ? O.deptName(p, id.id) : lab;
  };
  O.rolesOf = (p, id) => { const d = byId(p.composed, id) || (p.items.map((i) => i.org && byId(i.org.composed, id)).find(Boolean)); return d ? d.roles : []; };

  // 加部门时三样说明生成的 Prompt 底稿
  O.promptDraft = (name, goal, judge, how) => ['你是「' + name + '」部门。', '你对这件事负责：' + goal, '你凭这些判断：' + judge, '你这样工作：' + how].join('\n');

  O.freeze = (c) => ({ form: c.form, formName: c.formName, version: O.version(c), core: O.coreDigest(c), composed: clone(c) });

  // ------------------------------------------------------------------ 草稿（存在这个浏览器里，不进事实）

  const DRAFTS = 'drafts';
  O.draft = {
    all: () => Y19.store.get(DRAFTS, {}, true),
    get(pid) { return O.draft.all()[pid] || null; },
    set(pid, d) { const a = O.draft.all(); a[pid] = d; Y19.store.set(DRAFTS, a, true); },
    clear(pid) { const a = O.draft.all(); delete a[pid]; Y19.store.set(DRAFTS, a, true); },
    prune(ids) { const a = O.draft.all(); Object.keys(a).forEach((k) => { if (!ids.includes(k)) delete a[k]; }); Y19.store.set(DRAFTS, a, true); },
    start(p) { if (!O.draft.get(p.id)) O.draft.set(p.id, { base: p.version, form: p.org.form, changes: clone(p.org.changes), pending: {}, rebased: false }); return O.draft.get(p.id); },
    // 基准变了（别处采用了新的组织，或发布升级了形态）：按新的版本重新校验
    sync(p) { const d = O.draft.get(p.id); if (d && d.base !== p.version) { d.base = p.version; d.rebased = true; O.draft.set(p.id, d); } return d; }
  };
  O.draftCompose = (d) => O.compose({ form: d.form, changes: d.changes });
  O.draftCheck = function draftCheck(p, d) {
    const c = O.draftCompose(d);
    return { c, v: O.validate(c, O.ctxFor(p, d.pending)) };
  };

  // 采用（命令）：形态名、改动、理由、用户看到的组织版本，带命令身份
  O.adopt = function adopt(p, cmd) {
    if (cmd.key && p.org.keys[cmd.key]) return { ok: true, again: true, error: '' };
    if (!String(cmd.reason || '').trim()) return { ok: false, error: '理由不能为空' };
    if (cmd.base !== p.version) return { ok: false, stale: true, error: '你看到的组织版本已经被改过（现在是 ' + p.version + '），请按新的版本重新校验草稿' };
    const c = O.compose({ form: cmd.form, changes: cmd.changes });
    const v = O.validate(c, O.ctxFor(p, cmd.pending));
    if (v.rejects.length) return { ok: false, error: '有拒绝项，不能采用', rejects: v.rejects };
    const before = p.composed;
    p.org.history.push({ at: Y19.time.add(Y19.app.now(), 60 * (p.org.history.length + 1)), by: '你', fromVersion: p.version, toVersion: O.version(c), form: cmd.form, changes: clone(cmd.changes), reason: cmd.reason.trim(), diff: O.diff(before, c) });
    p.org.form = cmd.form; p.org.changes = clone(cmd.changes);
    Object.keys(cmd.pending || {}).forEach((id) => { if (c.depts.some((d) => d.id === id)) p.settings.dept[id] = clone(cmd.pending[id]); });
    if (cmd.key) p.org.keys[cmd.key] = true;
    O.refresh(p);
    return { ok: true, version: p.version };
  };

  // 新建事项：合成、校验，把合成结果整份冻结进事项；spec 可以是临时选的形态
  O.itemOrg = function itemOrg(p, formId) {
    const c = formId ? O.compose({ form: formId, changes: {} }) : p.composed;
    const v = O.validate(c, O.ctxFor(p));
    const noModel = c.depts.filter((d) => !O.ctxFor(p).modelOf(d, 0));
    const rejects = v.rejects.map((r) => r.text).concat(noModel.map((d) => '「' + d.name + '」还没有可用的模型'));
    return { c, v, rejects, org: O.freeze(c) };
  };
})();
