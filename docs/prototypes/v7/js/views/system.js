// 系统页：模型管理（D24 第 9.1 节）、运行与执行槽位（3.4A）、工具与扩展（3.2B、3.7）、元观察（Stage 5）、三个预留入口
(function () {
  'use strict';

  const Y7 = window.Y7;
  const esc = Y7.esc;
  const ui = Y7.ui;

  // 页面自己的界面状态（未提交的表单与选择）
  const st = {
    expanded: { 'opencode-go-responses': true },
    form: null,
    deptDraft: {},
    roleDraft: {},
    credRef: null,
    credMode: 'memory',
    json: null
  };

  const DEPTS3 = ['product', 'engineering', 'quality'];
  const CRED_LABELS = { missing: '缺失', memory: '内存', env: '环境', dotenv: '.env' };
  const CRED_NOTES = { memory: '只在本进程有效，重启后需重新提供', env: '宿主进程环境', dotenv: '.yudao/.env' };
  const METHODS = ['effort', 'adaptive', 'budget'];
  const MODEL_COMMANDS = ['saveConnection', 'deleteConnection', 'testConnection', 'testModel', 'fetchModels', 'addCandidate', 'acceptCapacity', 'saveDefinition', 'removeDefinition'];

  function rerender() {
    Y7.renderContent(true);
  }

  function catalogRaw() {
    return Y7.data.catalog;
  }

  function protocolOptions() {
    const list = ['responses', 'chat', 'messages'];
    if (Y7.atLeast('s5')) list.push('decision');
    return list;
  }

  function scheme(id) {
    const found = catalogRaw().presets.schemes.find((item) => item.id === id);
    if (!found) throw new Error('未知服务方案：' + id);
    return found;
  }

  function presetBase(schemeId, protocol) {
    const entry = scheme(schemeId).protocols.find((item) => item.protocol === protocol);
    return entry ? entry.baseUrl : '';
  }

  function deptList() {
    return Y7.atLeast('s5') ? DEPTS3.concat('operations') : DEPTS3;
  }

  function reasoningText(reasoning) {
    if (!reasoning || !reasoning.levels || !reasoning.levels.length) return '<span class="y7-muted">未声明（请求不带推理参数）</span>';
    return '<span class="y7-levels">' + reasoning.levels.map((level) => '<span class="y7-level' + (level === reasoning.defaultLevel ? ' is-default' : '') + '">' + esc(level) + '</span>').join('') + '</span>' +
      '<small class="y7-muted">默认 ' + esc(reasoning.defaultLevel) + ' · ' + esc(reasoning.method) + '</small>';
  }

  function credentialStatus(cred, ref) {
    if (!ref) return ui.status('admitted', '无需凭据');
    if (!cred || cred.state === 'missing') return ui.status('unusable', '凭据缺失');
    const base = ui.status(cred.rejected ? 'unusable' : 'admitted', CRED_LABELS[cred.state] + (cred.rejected ? ' · 上游拒绝' : ''));
    return base;
  }

  function effectiveCredState(cred) {
    if (cred.sources.memory) return 'memory';
    if (cred.sources.env) return 'env';
    if (cred.sources.dotenv) return 'dotenv';
    return 'missing';
  }

  function recomputeCredential(cred) {
    cred.state = effectiveCredState(cred);
    cred.rejected = cred.state !== 'missing' && cred.rejectedSource === cred.state;
    cred.note = cred.state === 'missing' ? '没有任何来源' : CRED_NOTES[cred.state] + (cred.rejected ? ' · 上游拒绝（HTTP 401）' : '');
  }

  function bumpVersion(version) {
    const n = version ? Number(String(version).replace(/\D/g, '')) || 0 : 0;
    return 'k' + (n + 1);
  }

  // ---------------------------------------------------------------------------
  // 引用与影响范围（第 4.4、4.5 节）

  function referrersOf(definitionIds) {
    const ids = new Set(definitionIds);
    const out = [];
    const cat = Y7.resolve(catalogRaw());
    Object.keys(cat.departmentDefaults).forEach((dept) => {
      const entry = cat.departmentDefaults[dept];
      if (entry && entry.definition && ids.has(entry.definition)) out.push({ kind: '部门默认', text: '部门默认 · ' + Y7.deptLabel(dept), definition: entry.definition });
    });
    if (cat.roleDefaults) {
      Object.keys(cat.roleDefaults).forEach((roleId) => {
        const entry = cat.roleDefaults[roleId];
        if (entry && entry.definition && ids.has(entry.definition)) out.push({ kind: '角色默认', text: '角色默认 · ' + roleName(roleId), definition: entry.definition });
      });
    }
    Object.keys(Y7.data.projectSettings).forEach((projectId) => {
      const project = Y7.raw.project(projectId);
      const settings = Y7.data.projectSettings[projectId];
      Object.keys(settings.departments).forEach((dept) => {
        const entry = settings.departments[dept];
        if (entry.model && ids.has(entry.model)) out.push({ kind: '项目部门设置', text: project.name + ' · ' + Y7.deptLabel(dept), definition: entry.model });
      });
      if (Y7.atLeast('s4') && settings.roles) {
        Object.keys(settings.roles).forEach((dept) => {
          if (!Array.isArray(settings.roles[dept])) return;
          settings.roles[dept].forEach((entry) => {
            if (entry.model && ids.has(entry.model)) out.push({ kind: '项目角色设置', text: project.name + ' · ' + roleName(entry.roleId), definition: entry.model });
          });
        });
      }
    });
    return out;
  }

  function activeUsers(definitionIds) {
    const ids = new Set(definitionIds);
    const out = [];
    Y7.resolve(Y7.data.workItems).forEach((item) => {
      if (!['in_progress', 'queued'].includes(item.status)) return;
      const project = Y7.project(item.projectId);
      if (!project) return;
      DEPTS3.forEach((dept) => {
        const target = Y7.model.resolve(item.projectId, dept);
        if (target.definition && ids.has(target.definition)) out.push(project.name + ' · ' + item.title + ' · ' + Y7.deptLabel(dept) + '部门');
      });
    });
    return out;
  }

  function roleName(roleId) {
    const catalog = catalogRaw().roleCatalog;
    for (const dept of DEPTS3) {
      const found = (catalog[dept] || []).find((role) => role.id === roleId);
      if (found) return found.name;
    }
    return roleId;
  }

  function impactHtml(definitionIds, reason) {
    const defs = definitionIds.map((id) => Y7.model.definition(id)).filter(Boolean);
    const refs = referrersOf(definitionIds);
    const users = activeUsers(definitionIds);
    return '<p>' + esc(reason) + '</p>' +
      '<h3 class="y7-h3">回到候选的模型访问定义</h3><ul class="y7-list">' + defs.map((def) => '<li>' + esc(Y7.model.label(def.id)) + '</li>').join('') + '</ul>' +
      '<h3 class="y7-h3">引用方（引用保留，显示「无法使用：准入已作废」）</h3>' + (refs.length ? '<ul class="y7-list">' + refs.map((ref) => '<li>' + esc(ref.text) + ' → ' + esc(Y7.model.label(ref.definition)) + '</li>').join('') + '</ul>' : '<p class="y7-muted">没有引用方</p>') +
      '<h3 class="y7-h3">正在使用它们的进行中事项</h3>' + (users.length ? '<ul class="y7-list">' + users.map((text) => '<li>' + esc(text) + '</li>').join('') + '</ul><p class="y7-note is-warn">这些部门的下一次模型请求会停在请求之前，事项进入待恢复，由你重新测试或另选模型。</p>' : '<p class="y7-muted">没有进行中的事项使用它们</p>');
  }

  // ---------------------------------------------------------------------------
  // 查询

  function connectionView(conn, cat) {
    const defs = cat.definitions.filter((def) => def.connectionId === conn.id);
    const admitted = defs.filter((def) => def.admission || (def.admissionByPoint && def.admissionByPoint.some((p) => p.calibrated))).length;
    const list = cat.candidates[conn.id];
    const listed = list ? list.ids.filter((id) => !defs.some((def) => def.upstreamModel === id)).length : 0;
    const cred = conn.credentialRef ? cat.credentials.find((item) => item.ref === conn.credentialRef) || null : null;
    return Object.assign({}, conn, {
      protocolLabel: Y7.PROTOCOL_LABELS[conn.protocol],
      schemeName: scheme(conn.scheme).name,
      definitions: defs,
      admittedCount: admitted,
      candidateCount: defs.length - admitted + listed,
      credential: cred,
      lastTest: cat.connectionTests[conn.id] || null,
      candidateList: list || null
    });
  }

  Y7.queries.register('catalog', () => {
    if (!Y7.atLeast('s3')) return { current: Y7.resolve(catalogRaw().current) };
    const cat = Y7.resolve(catalogRaw());
    delete cat.current;
    cat.connections = cat.connections.map((conn) => connectionView(conn, cat));
    cat.admittedDefinitions = cat.definitions.filter((def) => def.admission);
    return cat;
  });

  Y7.queries.register('runtime.slots', () => {
    const runtime = Y7.resolve(Y7.data.runtime);
    const describe = (workItemId) => {
      const item = Y7.workItem(workItemId);
      const project = item ? Y7.project(item.projectId) : null;
      const run = item ? Y7.run(item.runId) : null;
      return { item, project, run };
    };
    return {
      total: runtime.slots.total,
      defaultTotal: 3,
      used: runtime.slots.used.map((entry) => Object.assign({}, entry, describe(entry.workItemId), { roleName: entry.role ? roleName(entry.role) : null })),
      queue: runtime.queue.map((entry) => Object.assign({}, entry, describe(entry.workItemId), { waitSec: Y7.ui.since(entry.since) })),
      restartNote: runtime.restartNote,
      restartedAt: Y7.data.service ? Y7.data.service.restartedAt : null,
      unit: Y7.atLeast('s4') ? 'role' : 'run'
    };
  });

  Y7.queries.register('tools.registry', () => {
    const tools = Y7.resolve(Y7.data.tools);
    const grants = [];
    Y7.resolve(Y7.data.projects).forEach((project) => {
      (Y7.data.projectSettings[project.id].tools || []).forEach((grant) => grants.push(Object.assign({ projectId: project.id, projectName: project.name }, grant)));
    });
    return Object.assign(tools, { grants });
  });

  Y7.queries.register('meta.observations', () => {
    const meta = Y7.resolve(Y7.data.meta);
    const label = (projectId, workItemId) => {
      const project = Y7.project(projectId);
      const item = workItemId ? Y7.workItem(workItemId) : null;
      return (project ? project.name : projectId) + (item ? ' · ' + item.title : '');
    };
    meta.findings = meta.findings.map((entry) => Object.assign({ where: label(entry.projectId, entry.workItemId) }, entry));
    meta.judgments = meta.judgments.map((entry) => Object.assign({ where: label(entry.projectId, entry.workItemId) }, entry));
    return meta;
  });

  // ---------------------------------------------------------------------------
  // 页面公共部分

  function pageHead(eyebrow, title, subtitle, actions) {
    return '<header class="y7-page-head"><div class="y7-page-titles"><p class="y7-eyebrow">' + esc(eyebrow) + '</p><h1>' + esc(title) + '</h1>' +
      (subtitle ? '<p class="y7-subtitle">' + subtitle + '</p>' : '') + '</div>' +
      (actions ? '<div class="y7-page-actions">' + actions + '</div>' : '') + '</header>';
  }

  // ---------------------------------------------------------------------------
  // 模型管理：「当前」档显示现有实现

  function currentModelsPage() {
    const cur = Y7.query('catalog').current;
    const changes = [
      ['入口与标题', '左侧栏「模型管理」；顶栏按钮、路径与页面标题为「模型与 Provider」；副标题「' + cur.subtitle + '」', '路径只显示「模型管理」，提供「返回原界面」；修改从相关部门的下一次模型请求起生效，包括进行中的事项'],
      ['服务方案', '预置表 ' + cur.presetVersion + '：OpenCode Go 按协议列出完整端点、模型列表地址与官方文档；另有「自定义连接」', '只有 OpenCode Go 与自定义；按协议列出请求基址，请求路径由协议适配器拼接；显示 revision 与来源'],
      ['Provider 配置', '表格：名称、模型数、地址、凭据引用、状态；表单含模型列表地址与超时；协议在每个模型上声明', '一份连接一张卡片，默认收起；一份连接只声明一种协议，另一种协议另建一份；高级选项折叠'],
      ['候选模型', '来源地址、采集时间、模型 ID、建议协议与能力来源；候选不保存，需要建立访问定义并测试', '点击候选加入模型访问定义表；请求失败或没有地址时显示「候选未知」'],
      ['模型表与模型测试', '列：模型、协议、窗口、输出上限、准入与测试（未准入、已准入、测试结果不对应当前修订）', '增加推理档位声明；预填的容量逐行「接受」；准入按字段判断，准入列只读'],
      ['凭据', 'Key 输入框不回填；勾选「持久化到 .yudao/.env」才写入文件；保存 Key、清除内存覆盖、删除持久凭据', '写入方式改为「只在本进程有效」「写入 .env」两个选项；显示凭据状态与来源'],
      ['就绪状态条', '配置、凭据、准入、额度四项分开显示；额度显示为未知', 'D24 未改动这一项'],
      ['部门模型选择', '产品、工程、质检各选一个已准入模型；新事项使用，在途事项沿用创建时快照', '改为页面底部的「部门默认」，带请求档位；每个项目可以在部门设置中另选；从下一次模型请求起生效'],
      ['重新读取、导入与导出', '「重新读取」「导入 JSON」「导出」；文件更新未生效时保留当前修订', '编辑 JSON 弹窗：格式化、重置、复制、导入、导出；与表单同一套校验，整份写入或整份拒绝']
    ];
    const summary = ui.table({
      columns: [
        { key: 'area', label: '区域', render: (row) => '<strong>' + esc(row[0]) + '</strong>' },
        { key: 'now', label: '现有页面的内容', render: (row) => esc(row[1]) },
        { key: 'next', label: 'Stage 3 与 D24 的改动', render: (row) => esc(row[2]) }
      ],
      rows: changes,
      className: 'y7-table-compare'
    });
    const intro = ui.note('「当前」档显示现有实现的模型页（页面名为「模型与 Provider」）。按 D24 改版后的模型管理在「Stage 3 与 D24」档查看。' +
      '<span class="y7-note-actions"><button type="button" class="y7-btn small primary" data-act="core.level" data-level="s3">切换到「Stage 3 与 D24」档</button></span>', 'info');
    const providers = ui.table({
      columns: [
        { key: 'name', label: '名称' }, { key: 'models', label: '模型数' },
        { key: 'baseUrl', label: '地址', render: (row) => ui.code(row.baseUrl) },
        { key: 'credentialRef', label: '凭据引用', render: (row) => ui.code(row.credentialRef) },
        { key: 'status', label: '状态' }
      ],
      rows: cur.providers
    });
    const models = ui.table({
      columns: [
        { key: 'provider', label: 'Provider' }, { key: 'model', label: '模型', render: (row) => ui.code(row.model) },
        { key: 'protocol', label: '协议' }, { key: 'window', label: '窗口', render: (row) => ui.num(row.window) },
        { key: 'maxOutput', label: '输出上限', render: (row) => ui.num(row.maxOutput) },
        { key: 'admission', label: '准入与测试', render: (row) => ui.status(row.admission === '已准入' ? 'admitted' : 'unknown', row.admission) }
      ],
      rows: cur.models
    });
    const depts = ui.table({
      columns: [
        { key: 'department', label: '部门', render: (row) => esc(Y7.deptLabel(row.department)) },
        { key: 'value', label: '所选模型（新事项创建时读取）' }
      ],
      rows: cur.departments
    });
    return pageHead('系统', '模型管理', '现有实现：' + esc(cur.title) + ' · 目录修订 ' + cur.revision, '') +
      intro +
      ui.block({ title: '现有实现与 D24 的改动', tag: '当前', query: 'catalog', command: '无', body: summary }) +
      ui.block({ title: '就绪状态条（现有）', tag: '当前', query: 'catalog', body: ui.kv(cur.readiness.map((pair) => [pair[0], esc(pair[1])])) }) +
      ui.block({ title: 'Provider 配置（现有）', tag: '当前', query: 'catalog', command: 'saveProvider（现有）', body: providers }) +
      ui.block({ title: '模型表（现有，协议在每个模型上）', tag: '当前', query: 'catalog', command: 'testModel（现有）', body: models }) +
      ui.block({ title: '三个部门的模型选择（现有）', tag: '当前', query: 'catalog', command: 'saveBindings（现有）', body: depts + '<p class="y7-muted y7-small">现有页面说明：在途事项仍用创建时的快照。</p>' });
  }

  // ---------------------------------------------------------------------------
  // 模型管理：D24

  function modelsPage() {
    if (!Y7.atLeast('s3')) return currentModelsPage();
    const cat = Y7.query('catalog');
    const actions =
      ui.button({ label: '编辑 JSON', act: 'sys.openJson' }) +
      '<label class="y7-btn y7-file-btn"><input type="file" accept="application/json,.json" data-act="sys.pageImport"><span>导入</span></label>' +
      ui.button({ label: '导出', act: 'sys.export' }) +
      ui.button({ label: '添加 Provider 配置', kind: 'primary', icon: 'plus', act: 'sys.openAdd' });
    return pageHead('系统', '模型管理', 'Provider 配置、模型访问定义与部门默认。修改从相关部门的下一次模型请求起生效，包括进行中的事项；正在进行的请求照常完成。', actions) +
      fileBlock(cat) +
      (st.form ? formBlock(cat) : '') +
      connectionsBlock(cat) +
      credentialsBlock(cat) +
      departmentDefaultsBlock(cat) +
      roleDefaultsBlock(cat);
  }

  function fileBlock(cat) {
    const body = '<div class="y7-file-row">' +
      ui.kv([
        ['模型目录文件', ui.code(cat.file.path)],
        ['目录修订', esc(cat.file.revision)],
        ['最近读取', esc(ui.time(cat.file.reloadedAt))],
        ['服务方案预置表', 'revision ' + ui.code(cat.presets.revision) + ' · 来源 ' + esc(cat.presets.source)]
      ], 'is-inline') + '</div>' +
      (cat.file.reloadError
        ? ui.note('文件更新未生效：' + esc(cat.file.reloadError) + '；当前仍用修订 ' + esc(cat.file.revision) + '。', 'warn')
        : '<p class="y7-muted y7-small">合法的外部修改从下一次模型请求起生效；内容无效时保留上一个有效版本并显示原因；文件被删除时部门默认变为「未设置」。目录文档不含 API Key、准入记录与项目部门设置。</p>');
    return ui.block({ title: '目录文件', tag: 'D24', level: 's3', query: 'catalog', command: ['saveCatalogJson', 'importCatalog', 'exportCatalog'], body, className: 'is-compact' });
  }

  // Provider 配置卡片
  function connectionsBlock(cat) {
    const cards = cat.connections.map((conn) => connectionCard(conn, cat)).join('');
    return ui.block({
      title: 'Provider 配置', tag: 'D24', level: 's3', query: 'catalog', command: MODEL_COMMANDS,
      subtitle: '一份连接一张卡片，只声明一种协议；同一服务方案使用另一种协议时另建一份，默认沿用同一凭据引用。',
      body: '<div class="y7-conn-list">' + cards + '</div>'
    });
  }

  function connectionCard(conn, cat) {
    const open = Boolean(st.expanded[conn.id]);
    const decision = conn.protocol === 'decision';
    const summary = '<button type="button" class="y7-conn-summary" data-act="sys.toggleCard" data-connection-id="' + esc(conn.id) + '" aria-expanded="' + open + '">' +
      '<span class="y7-conn-name"><strong>' + esc(conn.name) + '</strong><small>' + esc(conn.schemeName) + ' · ' + esc(conn.protocolLabel) + '</small></span>' +
      '<span class="y7-conn-url">' + ui.code(conn.baseUrl) + '</span>' +
      '<span class="y7-conn-cred">' + credentialStatus(conn.credential, conn.credentialRef) + (conn.credentialRef ? '<small>' + esc(conn.credentialRef) + '</small>' : '') + '</span>' +
      '<span class="y7-conn-count">已准入 ' + conn.admittedCount + ' · 候选 ' + conn.candidateCount + '</span>' +
      ui.icon('chevron', 'y7-icon y7-chevron') + '</button>';
    if (!open) return '<article class="y7-conn-card">' + summary + '</article>';
    const test = conn.lastTest
      ? '<p class="y7-test-line ' + (conn.lastTest.ok ? 'is-ok' : 'is-fail') + '">' + ui.status(conn.lastTest.ok ? 'succeeded' : 'failed', conn.lastTest.text) + '<small>' + esc(ui.time(conn.lastTest.at)) + '</small></p>'
      : '<p class="y7-test-line y7-muted">尚未进行连接测试</p>';
    const actions = '<div class="y7-conn-actions">' +
      ui.button({ label: '编辑', kind: 'small', act: 'sys.openEdit', data: { connectionId: conn.id } }) +
      ui.button({ label: '测试连接', kind: 'small', cmd: 'testConnection', data: { connectionId: conn.id } }) +
      ui.button({ label: '获取模型列表', kind: 'small', cmd: 'fetchModels', data: { connectionId: conn.id } }) +
      ui.button({ label: '删除', kind: 'small danger', act: 'sys.deleteConnection', data: { connectionId: conn.id } }) +
      '</div>';
    const decisionNote = decision ? ui.note('决策模型协议：准入以判定点为单位，依靠样本校准；校准通过的判定点由控制层自动推进。', 'info') : '';
    return '<article class="y7-conn-card is-open">' + summary + '<div class="y7-conn-body">' + actions + test + decisionNote +
      definitionsTable(conn, cat) + candidatesArea(conn) + '</div></article>';
  }

  function admissionCell(def, cat) {
    const lastTest = cat.modelTests[def.id];
    let html;
    if (def.admissionByPoint) {
      const calibrated = def.admissionByPoint.filter((point) => point.calibrated).length;
      html = ui.status(calibrated ? 'admitted' : 'candidate', '按判定点 ' + calibrated + '/' + def.admissionByPoint.length + ' 已校准') +
        '<small class="y7-muted">' + def.admissionByPoint.map((point) => esc(point.judgmentPointId) + (point.calibrated ? ' 已校准' : ' 未校准') + '（样本 ' + point.samples + '）').join('、') + '</small>';
    } else if (def.admission) {
      html = ui.status('admitted', '已准入') + '<small class="y7-muted">' + esc(ui.time(def.admission.testedAt)) + ' · 实际返回 ' + esc(def.admission.actualModel) + ' · ' + esc(def.admission.protocol) + '</small>';
    } else if (def.admissionRevoked) {
      html = ui.status('unusable', '准入已作废') + '<small class="y7-muted">' + esc(def.admissionRevoked.reason) + '</small>';
    } else {
      html = ui.status('candidate', '候选') + (def.capacityAccepted ? '<small class="y7-muted">容量已确认，等待模型测试</small>' : '<small class="y7-muted">容量尚未接受或修改</small>');
    }
    if (lastTest) html += '<small class="y7-test-mini ' + (lastTest.ok ? 'is-ok' : 'is-fail') + '">' + esc(lastTest.text) + '</small>';
    return '<div class="y7-cell-stack">' + html + '</div>';
  }

  function capacityCell(def, key) {
    const value = def[key];
    if (value === null || value === undefined) return '<span class="y7-warn-text">未填写</span>';
    return '<span class="' + (def.capacityAccepted ? '' : 'y7-prefill') + '">' + ui.num(value) + '</span>';
  }

  function definitionsTable(conn, cat) {
    const decision = conn.protocol === 'decision';
    const rows = conn.definitions;
    const table = ui.table({
      columns: [
        { key: 'upstreamModel', label: '上游模型 ID', render: (def) => ui.code(def.upstreamModel) + (def.prefill && !def.capacityAccepted ? '<small class="y7-muted y7-block-line">' + esc(def.prefill) + '</small>' : '') },
        { key: 'window', label: '窗口', render: (def) => capacityCell(def, 'window') },
        { key: 'maxOutput', label: '输出上限', render: (def) => capacityCell(def, 'maxOutput') },
        { key: 'reasoning', label: '推理档位声明', render: (def) => reasoningText(def.reasoning) },
        { key: 'admission', label: '准入', render: (def) => admissionCell(def, cat) },
        { key: 'ops', label: '操作', className: 'y7-col-actions', render: (def) => '<div class="y7-row-actions">' +
          (def.capacityAccepted ? '' : ui.button({ label: '接受', kind: 'small primary', cmd: 'acceptCapacity', data: { definitionId: def.id }, disabled: !def.window || !def.maxOutput, title: '确认窗口与输出上限' })) +
          ui.button({ label: '修改', kind: 'small', act: 'sys.editDefinition', data: { definitionId: def.id } }) +
          (decision ? '' : ui.button({ label: '模型测试', kind: 'small', cmd: 'testModel', data: { definitionId: def.id } })) +
          ui.button({ label: '移除', kind: 'small danger', act: 'sys.removeDefinition', data: { definitionId: def.id } }) + '</div>' }
      ],
      rows,
      empty: '还没有模型访问定义：获取模型列表后点击候选加入'
    });
    return '<div class="y7-def-table"><h3 class="y7-h3">模型访问定义</h3>' + table + '</div>';
  }

  function candidatesArea(conn) {
    const list = conn.candidateList;
    if (!list) return '<div class="y7-candidates"><h3 class="y7-h3">候选</h3><p class="y7-muted">尚未获取模型列表</p></div>';
    if (list.unknownReason) {
      return '<div class="y7-candidates"><h3 class="y7-h3">候选</h3>' + ui.status('unknown', '候选未知') + ' <span class="y7-muted">' + esc(list.unknownReason) + '（' + esc(ui.time(list.collectedAt)) + '）</span></div>';
    }
    const chips = list.ids.map((id) => {
      const exists = conn.definitions.some((def) => def.upstreamModel === id);
      return exists
        ? '<span class="y7-chip is-done">' + esc(id) + '<small>已加入</small></span>'
        : '<button type="button" class="y7-chip" data-act="sys.addCandidate" data-connection-id="' + esc(conn.id) + '" data-model="' + esc(id) + '">' + ui.icon('plus') + esc(id) + '</button>';
    }).join('');
    return '<div class="y7-candidates"><h3 class="y7-h3">候选</h3><p class="y7-muted y7-small">来源 ' + ui.code(list.source) + ' · 采集于 ' + esc(ui.time(list.collectedAt)) + '；点击候选加入模型访问定义表，接受或修改容量并通过模型测试后才能选用。</p><div class="y7-chip-row">' + chips + '</div></div>';
  }

  // 添加或编辑 Provider 配置
  function formBlock(cat) {
    const f = st.form;
    const sch = scheme(f.scheme);
    const schemeButtons = cat.presets.schemes.map((item) =>
      '<button type="button" class="y7-pill' + (item.id === f.scheme ? ' is-on' : '') + '" data-act="sys.formScheme" data-scheme="' + esc(item.id) + '" aria-pressed="' + (item.id === f.scheme) + '">' + esc(item.name) + '</button>'
    ).join('');
    const schemeInfo = f.scheme === 'custom'
      ? '<p class="y7-muted y7-small">自定义：不使用预置表，地址、凭据引用与模型列表地址由你填写。</p>'
      : ui.kv([
        ['预置表', 'revision ' + ui.code(cat.presets.revision) + ' · 来源 ' + esc(cat.presets.source)],
        ['认证方式', esc(sch.auth)],
        ['必需请求头', esc(sch.headers.join('、'))],
        ['文档', ui.code(sch.docsUrl)],
        ['模型列表地址', ui.code(sch.modelsUrl)]
      ], 'is-inline');
    const protocolSelect = '<select class="y7-select" data-act="sys.formProtocol" id="y7-form-protocol">' + protocolOptions().map((p) =>
      '<option value="' + p + '"' + (p === f.protocol ? ' selected' : '') + (f.scheme !== 'custom' && !sch.protocols.some((item) => item.protocol === p) ? ' disabled' : '') + '>' + esc(Y7.PROTOCOL_LABELS[p]) + (p === 'decision' ? '（Stage 5）' : '') + '</option>'
    ).join('') + '</select>';
    const presetUrl = f.scheme !== 'custom';
    const creds = Y7.resolve(cat.credentials).map((cred) => '<option value="' + esc(cred.ref) + '"></option>').join('');
    const original = f.mode === 'edit' ? Y7.model.connection(f.connectionId) : null;
    const invalidating = original ? invalidatingChanges(original, f) : [];
    const body = '<div class="y7-form">' +
      '<div class="y7-field"><span>服务方案</span><div class="y7-pill-row">' + schemeButtons + '</div>' + schemeInfo + '</div>' +
      '<div class="y7-grid-2">' +
        '<label class="y7-field"><span>名称</span><input class="y7-input" type="text" value="' + esc(f.name) + '" data-act="sys.formField" data-field="name" placeholder="例如：OpenCode Go · Messages"></label>' +
        '<label class="y7-field"><span>协议</span>' + protocolSelect +
          (Y7.atLeast('s5') ? '<small class="y7-muted">决策模型协议：准入以判定点为单位</small>' : '<small class="y7-muted">一份 Provider 配置只声明一种协议</small>') + '</label>' +
        '<label class="y7-field"><span>地址（请求基址）</span><input class="y7-input" type="url" value="' + esc(f.baseUrl) + '" data-act="sys.formField" data-field="baseUrl"' + (presetUrl ? ' readonly' : '') + ' placeholder="https://…/v1">' +
          '<small class="y7-muted">' + (presetUrl ? '取自预置表中该协议的请求基址；请求路径由协议适配器拼接' : '由你填写该协议的请求基址') + '</small></label>' +
        '<label class="y7-field"><span>凭据引用</span><input class="y7-input" type="text" list="y7-cred-refs" value="' + esc(f.credentialRef || '') + '" data-act="sys.formField" data-field="credentialRef" placeholder="留空表示无需凭据"><datalist id="y7-cred-refs">' + creds + '</datalist>' +
          '<small class="y7-muted">Key 在下方「凭据」区保存，表单不保存 Key</small></label>' +
      '</div>' +
      '<details class="y7-details"' + (f.advancedOpen ? ' open' : '') + '><summary>高级选项</summary><div class="y7-grid-2">' +
        '<label class="y7-field"><span>超时（秒）</span><input class="y7-input" type="number" min="1" value="' + esc(f.timeoutSec) + '" data-act="sys.formField" data-field="timeoutSec"></label>' +
        '<label class="y7-field"><span>模型列表地址</span><input class="y7-input" type="url" value="' + esc(f.modelsUrl || '') + '" data-act="sys.formField" data-field="modelsUrl" placeholder="' + esc(sch.modelsUrl ? '留空时使用服务方案的地址：' + sch.modelsUrl : '留空表示没有模型列表地址') + '"></label>' +
      '</div></details>' +
      (f.mode === 'add'
        ? '<div class="y7-field"><span>模型访问定义</span>' + ui.empty('打开时模型访问定义表为空。保存后在卡片中获取模型列表，点击候选加入。') + '</div>'
        : '<p class="y7-muted y7-small">模型访问定义在卡片中编辑。</p>') +
      (invalidating.length ? ui.note('这次修改的' + esc(invalidating.join('、')) + '会作废该连接下全部定义的准入；保存前会列出受影响的定义、引用方与进行中事项。', 'warn') : '') +
      '</div>';
    const actions = ui.button({ label: '取消', act: 'sys.cancelForm' }) +
      (f.mode === 'edit' ? ui.button({ label: '测试连接', cmd: 'testConnection', data: { connectionId: f.connectionId }, title: '只测试已保存的连接' }) : '') +
      ui.button({ label: '保存', kind: 'primary', act: 'sys.saveForm' });
    return ui.block({
      title: f.mode === 'add' ? '添加 Provider 配置' : '编辑 Provider 配置', tag: 'D24', level: 's3', query: 'catalog', command: 'saveConnection',
      body, actions, className: 'y7-form-block', id: 'y7-conn-form'
    });
  }

  function invalidatingChanges(original, f) {
    const out = [];
    if ((original.baseUrl || '') !== (f.baseUrl || '')) out.push('地址');
    if ((original.credentialRef || '') !== (f.credentialRef || '')) out.push('凭据引用');
    if (original.protocol !== f.protocol) out.push('协议');
    return out;
  }

  // 凭据
  function credentialsBlock(cat) {
    const refs = [];
    cat.credentials.forEach((cred) => refs.push(cred.ref));
    cat.connections.forEach((conn) => { if (conn.credentialRef && !refs.includes(conn.credentialRef)) refs.push(conn.credentialRef); });
    const rows = refs.map((ref) => {
      const cred = cat.credentials.find((item) => item.ref === ref) || { ref, state: 'missing', sources: {}, version: null, rejected: false, note: '没有任何来源' };
      const users = cat.connections.filter((conn) => conn.credentialRef === ref).map((conn) => conn.name);
      return Object.assign({ users }, cred);
    });
    if (!st.credRef || !refs.includes(st.credRef)) st.credRef = refs[0] || null;
    const table = ui.table({
      columns: [
        { key: 'ref', label: '凭据引用', render: (row) => ui.code(row.ref) },
        { key: 'state', label: '状态与来源', render: (row) => '<div class="y7-cell-stack">' + credentialStatus(row, row.ref) + '<small class="y7-muted">' + esc(row.note) + '</small></div>' },
        { key: 'users', label: '引用它的 Provider 配置', render: (row) => esc(row.users.join('、') || '—') },
        { key: 'version', label: '非敏感版本', render: (row) => row.version ? ui.code(row.version) : '' }
      ],
      rows
    });
    const form = '<div class="y7-cred-form">' +
      '<label class="y7-field"><span>凭据引用</span><select class="y7-select" id="y7-cred-ref" data-act="sys.credRef">' + refs.map((ref) => '<option value="' + esc(ref) + '"' + (ref === st.credRef ? ' selected' : '') + '>' + esc(ref) + '</option>').join('') + '</select></label>' +
      '<label class="y7-field"><span>API Key</span><input class="y7-input" type="password" id="y7-cred-key" autocomplete="off" value="" placeholder="输入新的 Key；已保存的 Key 不回填"></label>' +
      '<fieldset class="y7-field y7-radio-row"><legend>写入方式</legend>' +
        '<label><input type="radio" name="y7-cred-mode" value="memory" data-act="sys.credMode"' + (st.credMode === 'memory' ? ' checked' : '') + '> 只在本进程有效</label>' +
        '<label><input type="radio" name="y7-cred-mode" value="dotenv" data-act="sys.credMode"' + (st.credMode === 'dotenv' ? ' checked' : '') + '> 写入 .env</label></fieldset>' +
      '<div class="y7-row">' + ui.button({ label: '保存 Key', kind: 'primary', act: 'sys.saveKey' }) +
        ui.button({ label: '清除内存覆盖', act: 'sys.clearOverride' }) +
        ui.button({ label: '删除持久凭据', kind: 'danger', act: 'sys.removePersisted' }) + '</div>' +
      '</div>';
    return ui.block({
      title: '凭据', tag: 'D24', level: 's3', query: 'catalog', command: ['saveCredential', 'clearCredentialOverride', 'removePersistedCredential'],
      subtitle: 'Key 输入框始终为空，不回填；内存中的临时 Key 优先于宿主环境与 .env。Key 更换从下一次模型请求起生效，同一凭据引用下更换 Key 不改变准入。',
      body: '<div class="y7-grid-cred">' + table + form + '</div>'
    });
  }

  // 部门默认
  function modelSelect(attrs, selected, admitted, cat, placeholder) {
    const groups = cat.connections.map((conn) => {
      const defs = admitted.filter((def) => def.connectionId === conn.id);
      if (!defs.length) return '';
      return '<optgroup label="' + esc(conn.name) + '">' + defs.map((def) => '<option value="' + esc(def.id) + '"' + (def.id === selected ? ' selected' : '') + '>' + esc(def.upstreamModel) + '</option>').join('') + '</optgroup>';
    }).join('');
    const orphan = selected && !admitted.some((def) => def.id === selected)
      ? '<option value="' + esc(selected) + '" selected disabled>' + esc(Y7.model.label(selected)) + '（无法使用）</option>'
      : '';
    return '<select class="y7-select" ' + attrs + '><option value=""' + (selected ? '' : ' selected') + '>' + esc(placeholder) + '</option>' + orphan + groups + '</select>';
  }

  function levelSelect(attrs, definitionId, selected) {
    const def = definitionId ? Y7.model.definition(definitionId) : null;
    const levels = def && def.reasoning ? def.reasoning.levels : [];
    if (!levels.length) {
      return '<select class="y7-select" ' + attrs + ' disabled><option>—</option></select><small class="y7-muted">' + (def ? '该模型未声明推理档位，请求不带推理参数' : '先选择模型') + '</small>';
    }
    return '<select class="y7-select" ' + attrs + '><option value=""' + (selected ? '' : ' selected') + '>空（使用模型的默认档位 ' + esc(def.reasoning.defaultLevel) + '）</option>' +
      levels.map((level) => '<option value="' + level + '"' + (level === selected ? ' selected' : '') + '>' + level + '</option>').join('') + '</select>';
  }

  function referenceStatus(definitionId) {
    if (!definitionId) return ui.status('idle', '未设置');
    const problem = Y7.model.problemOf(definitionId);
    if (problem) return ui.status('unusable', '无法使用：' + problem);
    return ui.status('admitted', '已准入');
  }

  function departmentDefaultsBlock(cat) {
    const admitted = cat.admittedDefinitions;
    const cards = deptList().map((dept) => {
      const saved = cat.departmentDefaults[dept] || { definition: null, level: null };
      const draft = st.deptDraft[dept] || { definition: saved.definition, level: saved.level };
      const dirty = draft.definition !== saved.definition || draft.level !== saved.level;
      return '<article class="y7-dept-card' + (dept === 'operations' ? ' is-ops' : '') + '">' +
        '<header><h3>' + esc(Y7.deptLabel(dept)) + '</h3>' + (dept === 'operations' ? ui.tag('Stage 5') : '') + '</header>' +
        '<div class="y7-dept-current"><span class="y7-muted">当前</span><strong>' + esc(saved.definition ? Y7.model.label(saved.definition) : '未设置') + '</strong>' +
          (saved.level ? '<span class="y7-level is-default">' + esc(saved.level) + '</span>' : '') + referenceStatus(saved.definition) + '</div>' +
        '<label class="y7-field"><span>模型</span>' + modelSelect('data-act="sys.deptModel" data-department="' + dept + '"', draft.definition, admitted, cat, '未设置') + '</label>' +
        '<label class="y7-field"><span>推理档位</span>' + levelSelect('data-act="sys.deptLevel" data-department="' + dept + '"', draft.definition, draft.level) + '</label>' +
        '<div class="y7-row">' + ui.button({ label: '保存', kind: dirty ? 'primary' : '', act: 'sys.saveDept', data: { department: dept }, disabled: !dirty }) +
          (dirty ? '<span class="y7-muted y7-small">有未保存的选择</span>' : '') + '</div>' +
        '</article>';
    }).join('');
    return ui.block({
      title: '部门默认', tag: 'D24', level: 's3', query: 'catalog', command: 'saveDepartmentDefault', id: 'y7-dept-defaults',
      subtitle: '从各部门下一次模型请求起生效，没有另选模型的项目同样生效，包括进行中的事项。',
      body: '<div class="y7-dept-grid">' + cards + '</div>'
    });
  }

  function roleDefaultsBlock(cat) {
    if (!Y7.atLeast('s4') || !cat.roleDefaults) return '';
    const admitted = cat.admittedDefinitions;
    const sections = DEPTS3.map((dept) => {
      const roles = cat.roleCatalog[dept];
      const rows = roles.map((role) => {
        const saved = cat.roleDefaults[role.id] || { definition: null, level: null };
        const draft = st.roleDraft[role.id] || { definition: saved.definition, level: saved.level };
        const dirty = draft.definition !== saved.definition || draft.level !== saved.level;
        return Object.assign({ saved, draft, dirty }, role);
      });
      const table = ui.table({
        columns: [
          { key: 'name', label: '角色', render: (row) => '<div class="y7-cell-stack"><strong>' + esc(row.name) + '</strong><small class="y7-muted">' + esc(row.duty) + '</small></div>' },
          { key: 'model', label: '模型', render: (row) => modelSelect('data-act="sys.roleModel" data-role-id="' + row.id + '"', row.draft.definition, admitted, cat, '未设置（按部门设置）') + '<div>' + referenceStatus(row.saved.definition) + '</div>' },
          { key: 'level', label: '推理档位', render: (row) => levelSelect('data-act="sys.roleLevel" data-role-id="' + row.id + '"', row.draft.definition, row.draft.level) },
          { key: 'ops', label: '操作', className: 'y7-col-actions', render: (row) => ui.button({ label: '保存', kind: row.dirty ? 'small primary' : 'small', act: 'sys.saveRole', data: { roleId: row.id }, disabled: !row.dirty }) }
        ],
        rows
      });
      return '<section class="y7-role-section"><h3 class="y7-h3">' + esc(Y7.deptLabel(dept)) + '部门</h3>' + table + '</section>';
    }).join('');
    return ui.block({
      title: '角色默认', tag: 'Stage 4', level: 's4', query: 'catalog', command: 'saveRoleDefault',
      subtitle: '解析顺序：项目角色设置、角色默认、项目部门设置、部门默认，取第一个写入了的。角色默认为未设置时，按部门的设置选择模型。',
      body: sections
    });
  }

  // ---------------------------------------------------------------------------
  // 编辑 JSON：目录文档（不含 API Key、准入记录与项目部门设置）

  function catalogDocument() {
    const cat = Y7.resolve(catalogRaw());
    const doc = {
      connections: cat.connections.map((conn) => ({
        id: conn.id, name: conn.name, scheme: conn.scheme, protocol: conn.protocol, baseUrl: conn.baseUrl,
        credentialRef: conn.credentialRef, timeoutSec: conn.timeoutSec, modelsUrl: conn.modelsUrl
      })),
      definitions: cat.definitions.map((def) => ({
        id: def.id, connectionId: def.connectionId, upstreamModel: def.upstreamModel, window: def.window, maxOutput: def.maxOutput,
        reasoning: def.reasoning ? { levels: def.reasoning.levels.slice(), defaultLevel: def.reasoning.defaultLevel, method: def.reasoning.method } : null
      })),
      departmentDefaults: {}
    };
    deptList().forEach((dept) => {
      const entry = cat.departmentDefaults[dept];
      const def = entry && entry.definition ? Y7.model.definition(entry.definition) : null;
      doc.departmentDefaults[dept] = entry && entry.definition ? { connection: def ? def.connectionId : null, definition: entry.definition, level: entry.level } : null;
    });
    if (Y7.atLeast('s4') && cat.roleDefaults) {
      doc.roleDefaults = {};
      Object.keys(cat.roleDefaults).forEach((roleId) => {
        const entry = cat.roleDefaults[roleId];
        const def = entry && entry.definition ? Y7.model.definition(entry.definition) : null;
        doc.roleDefaults[roleId] = entry && entry.definition ? { connection: def ? def.connectionId : null, definition: entry.definition, level: entry.level } : null;
      });
    }
    return doc;
  }

  const CONN_KEYS = ['id', 'name', 'scheme', 'protocol', 'baseUrl', 'credentialRef', 'timeoutSec', 'modelsUrl'];
  const DEF_KEYS = ['id', 'connectionId', 'upstreamModel', 'window', 'maxOutput', 'reasoning'];
  const REASONING_KEYS = ['levels', 'defaultLevel', 'method'];
  const REF_KEYS = ['connection', 'definition', 'level'];
  const ADMISSION_KEYS = ['admission', 'admissionRevoked', 'admissionByPoint', 'capacityAccepted'];

  function isObj(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function isUrl(text) {
    return typeof text === 'string' && /^https?:\/\/\S+$/.test(text);
  }

  function isPositiveInt(value) {
    return Number.isInteger(value) && value > 0;
  }

  // 与界面表单同一套校验（第 4.6 节）；返回 { errors, invalidations, removed }
  function validateDocument(doc) {
    const errors = [];
    const err = (path, message) => errors.push({ path, message });
    if (!isObj(doc)) {
      err('(根)', '目录文档必须是 JSON 对象');
      return { errors, invalidations: [], removed: [] };
    }
    const allowedTop = ['connections', 'definitions', 'departmentDefaults'].concat(Y7.atLeast('s4') ? ['roleDefaults'] : []);
    Object.keys(doc).forEach((key) => {
      if (!allowedTop.includes(key)) {
        err(key, key === 'apiKey' || key === 'keys' ? '目录文档不含 API Key，凭据在凭据区保存' : key === 'projectSettings' ? '目录文档不含项目部门设置' : '未知字段');
      }
    });
    ['connections', 'definitions', 'departmentDefaults'].forEach((key) => { if (!(key in doc)) err(key, '缺少必需字段'); });
    const connections = Array.isArray(doc.connections) ? doc.connections : [];
    if ('connections' in doc && !Array.isArray(doc.connections)) err('connections', '必须是数组');
    const connIds = new Set();
    const presets = catalogRaw().presets.schemes;
    connections.forEach((conn, i) => {
      const at = 'connections[' + i + ']';
      if (!isObj(conn)) { err(at, '必须是对象'); return; }
      Object.keys(conn).forEach((key) => { if (!CONN_KEYS.includes(key)) err(at + '.' + key, key === 'apiKey' ? '目录文档不含 API Key' : '未知字段'); });
      if (typeof conn.id !== 'string' || !conn.id) err(at + '.id', '必须是非空字符串');
      else if (connIds.has(conn.id)) err(at + '.id', '与其他 Provider 配置重复：' + conn.id);
      else connIds.add(conn.id);
      if (typeof conn.name !== 'string' || !conn.name.trim()) err(at + '.name', '必须是非空字符串');
      const sch = presets.find((item) => item.id === conn.scheme);
      if (!sch) err(at + '.scheme', '未知服务方案：' + conn.scheme + '（可选 ' + presets.map((item) => item.id).join('、') + '）');
      if (!protocolOptions().includes(conn.protocol)) err(at + '.protocol', '未知协议：' + conn.protocol + '（可选 ' + protocolOptions().join('、') + '）');
      else if (sch && sch.id !== 'custom' && !sch.protocols.some((item) => item.protocol === conn.protocol)) err(at + '.protocol', '服务方案 ' + sch.name + ' 没有这种协议');
      if (!isUrl(conn.baseUrl)) err(at + '.baseUrl', '必须是 http:// 或 https:// 地址');
      if (conn.credentialRef !== null && (typeof conn.credentialRef !== 'string' || !/^[A-Z][A-Z0-9_]*$/.test(conn.credentialRef))) err(at + '.credentialRef', '必须为 null，或由大写字母、数字与下划线组成的凭据引用');
      if (!isPositiveInt(conn.timeoutSec)) err(at + '.timeoutSec', '必须是正整数');
      if (typeof conn.modelsUrl !== 'string' || (conn.modelsUrl && !isUrl(conn.modelsUrl))) err(at + '.modelsUrl', '必须是空字符串或 http(s) 地址');
    });
    const definitions = Array.isArray(doc.definitions) ? doc.definitions : [];
    if ('definitions' in doc && !Array.isArray(doc.definitions)) err('definitions', '必须是数组');
    const defIds = new Set();
    definitions.forEach((def, i) => {
      const at = 'definitions[' + i + ']';
      if (!isObj(def)) { err(at, '必须是对象'); return; }
      Object.keys(def).forEach((key) => {
        if (DEF_KEYS.includes(key)) return;
        err(at + '.' + key, ADMISSION_KEYS.includes(key) ? '准入与容量确认不写在目录文档中：准入记录只由模型测试写入' : '未知字段');
      });
      if (typeof def.id !== 'string' || !def.id) err(at + '.id', '必须是非空字符串');
      else if (defIds.has(def.id)) err(at + '.id', '与其他模型访问定义重复：' + def.id);
      else defIds.add(def.id);
      if (!connIds.has(def.connectionId)) err(at + '.connectionId', '没有这个 Provider 配置：' + def.connectionId);
      if (typeof def.upstreamModel !== 'string' || !def.upstreamModel) err(at + '.upstreamModel', '必须是非空字符串');
      if (!isPositiveInt(def.window)) err(at + '.window', '窗口必须有值，并且是正整数');
      if (!isPositiveInt(def.maxOutput)) err(at + '.maxOutput', '输出上限必须有值，并且是正整数');
      else if (isPositiveInt(def.window) && def.maxOutput > def.window) err(at + '.maxOutput', '输出上限不能大于窗口（' + def.window + '）');
      if (def.reasoning !== null && def.reasoning !== undefined) {
        const r = def.reasoning;
        if (!isObj(r)) err(at + '.reasoning', '必须为 null 或对象');
        else {
          Object.keys(r).forEach((key) => { if (!REASONING_KEYS.includes(key)) err(at + '.reasoning.' + key, '未知字段'); });
          if (!Array.isArray(r.levels) || !r.levels.length) err(at + '.reasoning.levels', '必须是非空数组');
          else r.levels.forEach((level, j) => { if (!Y7.REASONING_LEVELS.includes(level)) err(at + '.reasoning.levels[' + j + ']', '未知推理档位：' + level + '（可选 ' + Y7.REASONING_LEVELS.join('、') + '）'); });
          if (!Array.isArray(r.levels) || !r.levels.includes(r.defaultLevel)) err(at + '.reasoning.defaultLevel', '默认档位必须是支持档位之一');
          if (!METHODS.includes(r.method)) err(at + '.reasoning.method', '推理参数方式必须是 ' + METHODS.join('、'));
        }
      } else if (def.reasoning === undefined) {
        err(at + '.reasoning', '缺少必需字段（没有声明时写 null）');
      }
    });
    // 与现有目录比较：会作废准入的修改（第 4.4 节）
    const invalidations = [];
    const docConn = {};
    connections.forEach((conn) => { if (isObj(conn)) docConn[conn.id] = conn; });
    definitions.forEach((def, i) => {
      if (!isObj(def)) return;
      const old = Y7.model.definition(def.id);
      if (!old || !old.admission) return;
      const oldConn = Y7.model.connection(old.connectionId);
      const newConn = docConn[def.connectionId];
      const reasons = [];
      if (old.connectionId !== def.connectionId) reasons.push('所属连接');
      if (old.upstreamModel !== def.upstreamModel) reasons.push('上游模型 ID');
      if ((old.reasoning ? old.reasoning.method : null) !== (isObj(def.reasoning) ? def.reasoning.method : null)) reasons.push('推理参数方式');
      if (newConn && oldConn) {
        if (oldConn.baseUrl !== newConn.baseUrl) reasons.push('连接地址');
        if ((oldConn.credentialRef || null) !== (newConn.credentialRef || null)) reasons.push('凭据引用');
        if (oldConn.protocol !== newConn.protocol) reasons.push('协议');
      }
      if (reasons.length) invalidations.push({ id: def.id, index: i, reasons });
    });
    const invalidIds = new Set(invalidations.map((item) => item.id));
    const admittedAfter = (id) => {
      const old = Y7.model.definition(id);
      return Boolean(old && old.admission && !invalidIds.has(id));
    };
    const checkRef = (at, entry) => {
      if (entry === null) return;
      if (!isObj(entry)) { err(at, '必须为 null 或对象'); return; }
      Object.keys(entry).forEach((key) => { if (!REF_KEYS.includes(key)) err(at + '.' + key, '未知字段'); });
      const def = definitions.find((item) => isObj(item) && item.id === entry.definition);
      if (!def) { err(at + '.definition', '没有这个模型访问定义：' + entry.definition); return; }
      if (def.connectionId !== entry.connection) err(at + '.connection', '定义 ' + entry.definition + ' 不属于连接 ' + entry.connection);
      if (!admittedAfter(entry.definition)) err(at + '.definition', '只能引用已准入的定义：' + entry.definition + (invalidIds.has(entry.definition) ? '（这次修改会作废它的准入）' : '（尚未准入）'));
      if (entry.level !== null && entry.level !== undefined) {
        const levels = isObj(def.reasoning) && Array.isArray(def.reasoning.levels) ? def.reasoning.levels : [];
        if (!levels.includes(entry.level)) err(at + '.level', '请求档位必须属于该定义声明的支持档位（' + (levels.join('、') || '未声明') + '）');
      }
    };
    if (!isObj(doc.departmentDefaults)) {
      if ('departmentDefaults' in doc) err('departmentDefaults', '必须是对象');
    } else {
      Object.keys(doc.departmentDefaults).forEach((dept) => {
        if (!deptList().includes(dept)) { err('departmentDefaults.' + dept, '未知部门'); return; }
        checkRef('departmentDefaults.' + dept, doc.departmentDefaults[dept]);
      });
    }
    if (doc.roleDefaults !== undefined) {
      if (!isObj(doc.roleDefaults)) err('roleDefaults', '必须是对象');
      else {
        const known = Object.keys(catalogRaw().roleDefaults).filter((key) => key !== 'level');
        Object.keys(doc.roleDefaults).forEach((roleId) => {
          if (!known.includes(roleId)) { err('roleDefaults.' + roleId, '未知角色'); return; }
          checkRef('roleDefaults.' + roleId, doc.roleDefaults[roleId]);
        });
      }
    }
    // 被移除的定义不能仍被项目部门设置引用（第 4.5 节）
    const visibleDefs = Y7.resolve(catalogRaw().definitions).map((def) => def.id);
    const removed = visibleDefs.filter((id) => !defIds.has(id));
    const blocked = referrersOf(removed).filter((ref) => ref.kind === '项目部门设置' || ref.kind === '项目角色设置');
    blocked.forEach((ref) => err('definitions', '移除的定义 ' + ref.definition + ' 仍被引用：' + ref.text));
    return { errors, invalidations, removed };
  }

  function applyDocument(doc, check) {
    const cat = catalogRaw();
    const keepHidden = (list) => list.filter((item) => Y7.isStage(item.level) && !Y7.atLeast(item.level));
    const levelOf = (list, id) => {
      const found = list.find((item) => item.id === id);
      return found && Y7.isStage(found.level) ? found.level : null;
    };
    const oldConnections = cat.connections;
    const oldDefinitions = cat.definitions;
    const invalid = {};
    check.invalidations.forEach((item) => { invalid[item.id] = item.reasons; });
    cat.connections = doc.connections.map((conn) => {
      const out = Object.assign({}, conn);
      const level = levelOf(oldConnections, conn.id);
      if (level) out.level = level;
      return out;
    }).concat(keepHidden(oldConnections));
    cat.definitions = doc.definitions.map((def) => {
      const old = oldDefinitions.find((item) => item.id === def.id) || null;
      const out = Object.assign({}, def);
      const level = levelOf(oldDefinitions, def.id);
      if (level) out.level = level;
      const capacityChanged = !old || old.window !== def.window || old.maxOutput !== def.maxOutput;
      out.capacityAccepted = old ? (old.capacityAccepted || capacityChanged) : true;
      if (old && old.prefill && !out.capacityAccepted) out.prefill = old.prefill;
      if (old && old.admissionByPoint) out.admissionByPoint = old.admissionByPoint;
      if (invalid[def.id]) {
        out.admission = null;
        out.admissionRevoked = { at: Y7.data.now, reason: '编辑 JSON 修改了' + invalid[def.id].join('、'), previous: old.admission };
      } else {
        out.admission = old ? old.admission : null;
        out.admissionRevoked = old ? old.admissionRevoked : null;
      }
      return out;
    }).concat(keepHidden(oldDefinitions));
    // 整份写入：文档中没有写的部门为「未设置」
    deptList().forEach((dept) => {
      const entry = doc.departmentDefaults[dept];
      const value = entry ? { definition: entry.definition, level: entry.level === undefined ? null : entry.level } : { definition: null, level: null };
      if (dept === 'operations') cat.departmentDefaults.levels.s5.operations = value;
      else cat.departmentDefaults[dept] = value;
    });
    if (doc.roleDefaults) {
      Object.keys(doc.roleDefaults).forEach((roleId) => {
        const entry = doc.roleDefaults[roleId];
        cat.roleDefaults[roleId] = entry ? { definition: entry.definition, level: entry.level === undefined ? null : entry.level } : { definition: null, level: null };
      });
    }
    cat.file.revision += 1;
    cat.file.reloadedAt = Y7.data.now;
  }

  // 解析用户输入的目录文档：JSON 语法错误是输入校验的结果，原样显示给用户（浏览器的错误信息带有行列位置）；其他错误照常抛出
  function parseDocument(text) {
    if (!text.trim()) return { error: '文档为空' };
    try {
      return { doc: JSON.parse(text) };
    } catch (e) {
      if (e instanceof SyntaxError) return { error: e.message };
      throw e;
    }
  }

  function jsonSaveCommand(name, params) {
    const parsed = parseDocument(params.text || '');
    if (parsed.error) return { ok: false, message: '整份拒绝：JSON 格式错误', errors: [{ path: '(文档)', message: parsed.error }] };
    const check = validateDocument(parsed.doc);
    if (check.errors.length) return { ok: false, message: '整份拒绝：' + check.errors.length + ' 处校验不通过，没有写入任何内容', errors: check.errors };
    if (check.invalidations.length && params.confirmed !== 'yes') {
      return { ok: false, message: '这次保存会作废 ' + check.invalidations.length + ' 个定义的准入，需要确认', needsConfirm: true, invalidations: check.invalidations };
    }
    applyDocument(parsed.doc, check);
    const paths = ['catalog'].concat(Y7.model.afterChange());
    return { ok: true, message: (name === 'importCatalog' ? '已导入目录文档' : '已保存目录文档') + '（修订 ' + catalogRaw().file.revision + '），从下一次模型请求起生效' + (check.invalidations.length ? '；' + check.invalidations.length + ' 个定义回到候选' : ''), paths };
  }

  function openJsonModal(text, source) {
    st.json = { text: text === undefined ? JSON.stringify(catalogDocument(), null, 2) : text, source: source || null, errors: [], confirm: null };
    renderJsonModal();
  }

  function renderJsonModal() {
    const j = st.json;
    const errors = j.errors.length
      ? '<div class="y7-json-errors" role="alert"><strong>整份拒绝，没有写入任何内容</strong><ul>' + j.errors.map((e) => '<li><code>' + esc(e.path) + '</code>' + esc(e.message) + '</li>').join('') + '</ul></div>'
      : '';
    const confirm = j.confirm
      ? '<div class="y7-json-errors is-warn" role="alert"><strong>这次保存会作废以下定义的准入</strong><ul>' + j.confirm.map((item) => '<li><code>' + esc(item.id) + '</code>修改了' + esc(item.reasons.join('、')) + '</li>').join('') + '</ul>' +
        impactHtml(j.confirm.map((item) => item.id), '引用保留，相关部门的下一次模型请求停在请求之前，事项进入待恢复。') + '</div>'
      : '';
    const body = '<p class="y7-muted y7-small">目录文档包含 Provider 配置、模型访问定义与部门默认' + (Y7.atLeast('s4') ? '、角色默认' : '') + '，格式与模型目录文件相同；不含 API Key、准入记录与项目部门设置。在 JSON 中修改容量等同于确认容量。' +
      (j.source ? ' 当前内容来自导入的文件「' + esc(j.source) + '」，保存前按同一套校验检查。' : '') + '</p>' +
      '<div class="y7-json-tools">' +
        ui.button({ label: '格式化', kind: 'small', act: 'sys.jsonFormat' }) +
        ui.button({ label: '重置', kind: 'small', act: 'sys.jsonReset' }) +
        ui.button({ label: '复制', kind: 'small', act: 'sys.jsonCopy' }) +
        '<label class="y7-btn small y7-file-btn"><input type="file" accept="application/json,.json" data-act="sys.jsonImport"><span>导入</span></label>' +
        ui.button({ label: '导出', kind: 'small', act: 'sys.export' }) +
      '</div>' +
      '<textarea class="y7-textarea y7-json" id="y7-json-text" spellcheck="false" data-act="sys.jsonEdit" aria-label="目录文档">' + esc(j.text) + '</textarea>' + errors + confirm;
    Y7.ui.modal({
      title: '编辑 JSON · 目录文档',
      wide: true,
      body,
      actions: [
        { label: '取消', close: true },
        { label: j.confirm ? '确认保存（作废 ' + j.confirm.length + ' 项准入）' : '保存', kind: j.confirm ? 'danger' : 'primary', act: 'sys.jsonSave' }
      ]
    });
  }

  function downloadText(name, text) {
    const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ---------------------------------------------------------------------------
  // 运行与执行槽位（3.4A）

  function runtimePage() {
    const data = Y7.query('runtime.slots');
    const lamps = Array.from({ length: data.total }, (_, i) => '<span class="y7-lamp' + (i < data.used.length ? ' is-on' : '') + '" title="' + (i < data.used.length ? '已占用' : '空闲') + '"></span>').join('');
    const options = [1, 2, 3, 4, 5, 6, 8].map((n) => '<option value="' + n + '"' + (n === data.total ? ' selected' : '') + '>' + n + '</option>').join('');
    const slots = '<div class="y7-slot-row"><div class="y7-lamps" aria-label="执行槽位占用">' + lamps + '</div>' +
      '<div class="y7-slot-count"><strong>' + data.used.length + ' / ' + data.total + '</strong><span class="y7-muted">已占用 / 槽位数' + (data.total !== data.defaultTotal ? '（默认 ' + data.defaultTotal + '）' : '（默认）') + '</span></div>' +
      '<label class="y7-field is-inline"><span>执行槽位数</span><select class="y7-select" id="y7-slot-total">' + options + '</select></label>' +
      ui.button({ label: '保存', kind: 'primary', act: 'sys.setSlots' }) + '</div>' +
      (data.unit === 'role'
        ? ui.note('Stage 4 档按角色任务占用执行槽位：每个进行中的角色任务占用一个槽位，没有空闲槽位时任务保持已分派。占用单位待确认：3.4A 工单按 run 计，多角色草案第 9 节按角色任务计。', 'info')
        : '<p class="y7-muted y7-small">每个进行中的 run 占用一个执行槽位；超出部分排队。</p>');
    const running = ui.table({
      columns: [
        { key: 'project', label: '项目', render: (row) => row.project ? '<button type="button" class="y7-link" data-go="' + Y7.paths.overview(row.project.id, row.item.id) + '">' + esc(row.project.name) + '</button>' : '' },
        { key: 'item', label: '事项', render: (row) => row.item ? esc(row.item.title) : '' },
        { key: 'department', label: data.unit === 'role' ? '部门 · 角色任务' : '部门', render: (row) => esc(Y7.deptLabel(row.department)) + (row.roleName ? ' · ' + esc(row.roleName) : '') },
        { key: 'state', label: '状态', render: (row) => row.item ? statusOf(row.item, row.run) : '' },
        { key: 'elapsed', label: '已用时间', render: (row) => row.run ? esc(ui.duration(row.run.elapsedSec)) + ' / ' + esc(ui.duration(row.run.limitSec)) : '' }
      ],
      rows: data.used,
      empty: '没有正在执行的事项'
    });
    const queue = ui.table({
      columns: [
        { key: 'position', label: '顺序', render: (row) => '<span class="y7-ticket">' + row.position + '</span>' },
        { key: 'project', label: '项目', render: (row) => row.project ? esc(row.project.name) : '' },
        { key: 'item', label: '事项', render: (row) => row.item ? '<button type="button" class="y7-link" data-go="' + Y7.paths.overview(row.project.id, row.item.id) + '">' + esc(row.item.title) + '</button>' : '' },
        { key: 'since', label: '排队开始', render: (row) => esc(ui.time(row.since)) },
        { key: 'wait', label: '等待时长', render: (row) => esc(ui.duration(row.waitSec)) },
        { key: 'ops', label: '操作', className: 'y7-col-actions', render: (row) => ui.button({ label: '取消排队', kind: 'small danger', cmd: 'cancelQueued', data: { workItemId: row.workItemId } }) }
      ],
      rows: data.queue,
      empty: '没有排队中的事项'
    });
    const restart = ui.kv([
      ['最近一次重启', esc(data.restartedAt ? ui.time(data.restartedAt) : '—')],
      ['队列状态', esc(data.restartNote)]
    ], 'is-rows');
    return pageHead('系统', '运行与执行槽位', '执行槽位由宿主设置控制；排队中与运行中的事项各自可以取消，互不干扰。', '') +
      ui.block({ title: '执行槽位', tag: '3.4A', level: 's3', query: 'runtime.slots', command: 'setSlots', body: slots }) +
      ui.block({ title: '正在执行', tag: '3.4A', level: 's3', query: 'runtime.slots', command: '无', body: running }) +
      ui.block({ title: '跨项目排队', tag: '3.4A', level: 's3', query: 'runtime.slots', command: 'cancelQueued', body: queue }) +
      ui.block({ title: '重启后的队列状态', tag: '3.4A', level: 's3', query: 'runtime.slots', body: restart });
  }

  function statusOf(item, run) {
    const s = Y7.workItemStatus(item, run);
    return ui.status(s.kind, s.text);
  }

  // ---------------------------------------------------------------------------
  // 工具与扩展（3.2B、3.7，设计待定）

  function toolsPage() {
    const reg = Y7.query('tools.registry');
    const pending = ui.note('<strong>设计待定</strong>：这一页的依据只有路线图与 Stage 3 计划的工作包说明，进入 3.2B、3.7 时细化。', 'warn');
    const recent = ui.table({
      columns: [
        { key: 'at', label: '时间', render: (row) => esc(ui.time(row.at)) },
        { key: 'where', label: '项目 · 事项', render: (row) => { const p = Y7.project(row.projectId); const w = Y7.workItem(row.workItemId); return esc((p ? p.name : row.projectId) + (w ? ' · ' + w.title : '')); } },
        { key: 'url', label: '地址', render: (row) => ui.code(row.url) },
        { key: 'result', label: '结果', render: (row) => ui.status(row.result.startsWith('已取回') ? 'succeeded' : row.result.startsWith('超出') ? 'pending' : 'cancelled', row.result) }
      ],
      rows: reg.network.recent
    });
    const grants = ui.table({
      columns: [
        { key: 'projectName', label: '项目' }, { key: 'label', label: '工具' },
        { key: 'scope', label: '授权范围' }, { key: 'approval', label: '超出授权时' }
      ],
      rows: reg.grants,
      empty: '没有项目授权'
    });
    const mcp = reg.mcp.map((server) => '<section class="y7-mcp"><h3 class="y7-h3">' + esc(server.name) + '</h3>' + ui.table({
      columns: [
        { key: 'name', label: '工具', render: (row) => ui.code(row.name) },
        { key: 'recovery', label: '恢复约定（结果未知时怎样核实）', render: (row) => row.recovery ? esc(row.recovery) : '<span class="y7-muted">没有恢复约定</span>' },
        { key: 'retry', label: '能否重复', render: (row) => row.recovery ? ui.status('admitted', row.retry) : ui.status('unusable', '不自动重试') }
      ],
      rows: server.tools
    }) + '</section>').join('');
    const hooks = ui.table({ columns: [{ key: 'name', label: '准入钩子' }, { key: 'effect', label: '作用' }], rows: reg.hooks });
    const observers = ui.table({ columns: [{ key: 'name', label: '只读观察者' }, { key: 'scope', label: '订阅范围' }], rows: reg.observers });
    return pageHead('系统', '工具与扩展', '网络取回、MCP 工具、准入钩子与只读观察者。', '') + pending +
      ui.block({ title: '网络取回', tag: '3.2B · 设计待定', level: 's3', query: 'tools.registry', command: ['authorizeTool', 'approveOnce'], subtitle: reg.network.scope, body: '<h3 class="y7-h3">各项目的授权</h3>' + grants + '<h3 class="y7-h3">最近的取回记录</h3>' + recent }) +
      ui.block({ title: 'MCP 工具', tag: '3.2B · 设计待定', level: 's3', query: 'tools.registry', command: 'authorizeTool', subtitle: '经官方 MCP SDK 接入，先成为已声明工具；没有恢复约定的工具不自动重试。', body: mcp }) +
      ui.block({ title: '准入钩子与只读观察者', tag: '3.7 · 设计待定', level: 's3', query: 'tools.registry', command: '无', body: '<div class="y7-grid-2"><div>' + hooks + '<p class="y7-muted y7-small">钩子只能收紧，不能授权。</p></div><div>' + observers + '<p class="y7-muted y7-small">观察者只订阅，不推进状态。</p></div></div>' });
  }

  // ---------------------------------------------------------------------------
  // 元观察（Stage 5）

  const RESULT_LABELS = { pass: ['admitted', '通过'], fail: ['failed', '不通过'], uncertain: ['unknown', '不确定'] };

  function resultStatus(result) {
    const pair = RESULT_LABELS[result];
    if (!pair) throw new Error('未知判定结果：' + result);
    return ui.status(pair[0], pair[1]);
  }

  function metaPage() {
    const meta = Y7.query('meta.observations');
    const stats = '<div class="y7-stat-grid">' + meta.flowStats.map((item) =>
      '<div class="y7-stat"><span>' + esc(item.label) + '</span><strong>' + item.count + '</strong><small>平均间隔 ' + esc(ui.duration(item.avgIntervalSec)) + '</small></div>'
    ).join('') + '</div>';
    const findings = ui.table({
      columns: [
        { key: 'where', label: '项目 · 事项' }, { key: 'rule', label: '规则' },
        { key: 'text', label: '审查结果', render: (row) => (row.ok ? ui.status('admitted', '符合') : ui.status('unusable', '不符合')) + ' ' + esc(row.text) },
        { key: 'at', label: '时间', render: (row) => esc(ui.time(row.at)) }
      ],
      rows: meta.findings
    });
    const points = ui.table({
      columns: [
        { key: 'id', label: '判定点', render: (row) => ui.code(row.id) },
        { key: 'question', label: '问题' },
        { key: 'calibrated', label: '校准状态', render: (row) => row.calibrated ? ui.status('admitted', '已校准') : ui.status('candidate', '未通过校准') },
        { key: 'lastResult', label: '最近判定', render: (row) => resultStatus(row.lastResult) },
        { key: 'probability', label: '概率 · 置信度', render: (row) => esc(row.probability.toFixed(2)) + ' · ' + esc(row.confidence.toFixed(2)) + ui.meter(row.confidence, 1, { warnAt: 2 }) },
        { key: 'route', label: '去向' }
      ],
      rows: meta.judgmentPoints
    });
    const judgments = ui.table({
      columns: [
        { key: 'at', label: '时间', render: (row) => esc(ui.time(row.at)) },
        { key: 'judgmentPointId', label: '判定点', render: (row) => ui.code(row.judgmentPointId) },
        { key: 'where', label: '项目 · 事项' }, { key: 'handoff', label: '交接' },
        { key: 'result', label: '结果', render: (row) => resultStatus(row.result) + ' <small class="y7-muted">置信度 ' + esc(row.confidence.toFixed(2)) + '</small>' },
        { key: 'route', label: '去向' }
      ],
      rows: meta.judgments.slice().reverse()
    });
    const decisions = meta.pendingDecisions.length
      ? meta.pendingDecisions.map((d) => '<article class="y7-decision"><header>' + ui.code(d.judgmentPointId) + '<strong>' + esc(d.question) + '</strong></header><div class="y7-row">' +
        d.options.map((option) => ui.button({ label: option, kind: 'small', cmd: 'decideJudgment', data: { decisionId: d.id, option } })).join('') + '</div></article>').join('')
      : ui.empty('没有等待你决定的判定');
    const decided = meta.decisions.length
      ? '<h3 class="y7-h3">已作出的决定</h3><ul class="y7-list">' + meta.decisions.map((d) => '<li>' + esc(ui.time(d.at)) + ' · ' + ui.code(d.judgmentPointId) + ' ' + esc(d.option) + '</li>').join('') + '</ul>'
      : '';
    return pageHead('系统', '元观察', '元观察与规则检查部门经只读观察接口订阅事件：流转统计、规则审查与判定点。判定点上的推进由控制层按事先规定的规则执行。', '') +
      ui.block({ title: '流转统计', tag: 'Stage 5', level: 's5', query: 'meta.observations', body: stats }) +
      ui.block({ title: '规则审查的不符合项', tag: 'Stage 5', level: 's5', query: 'meta.observations', body: findings }) +
      ui.block({ title: '判定点', tag: 'Stage 5', level: 's5', query: 'meta.observations', subtitle: '校准通过的判定点由控制层自动推进；未通过校准的判定点只记录。', body: points }) +
      ui.block({ title: '判定记录', tag: 'Stage 5', level: 's5', query: 'meta.observations', body: judgments }) +
      ui.block({ title: '置信度不足、等待你决定的判定', tag: 'Stage 5', level: 's5', query: 'meta.observations', command: 'decideJudgment', body: decisions + decided });
  }

  // ---------------------------------------------------------------------------
  // 预留入口

  const RESERVED = {
    nodes: { title: '节点', stage: 'Stage 6：分布式部署', result: '控制层与各部门可以部署在不同的服务器和平台上，任一节点故障后任务可以接续，不会重复推进' },
    evolution: { title: '演化', stage: 'Stage 7：受治理的系统演化', result: '根据运行证据提出组织或规则变更，独立验证、限定采用并可撤销' },
    lessons: { title: '经验', stage: '持续改进工作线', result: '从重复问题形成经过验证、可停用的跨任务经验，并证明收益' }
  };

  function reservedPage(ctx) {
    const info = RESERVED[ctx.route.params.which];
    if (!info) throw new Error('未知预留入口：' + ctx.route.params.which);
    return pageHead('预留入口', info.title, '', '') +
      ui.block({
        title: info.title, tag: info.stage, query: '无', command: '无', className: 'y7-reserved',
        body: ui.kv([['所属阶段', esc(info.stage)], ['产品结果', esc(info.result)], ['设计', '进入该阶段时设计']], 'is-rows')
      });
  }

  // ---------------------------------------------------------------------------
  // 页面注册

  Y7.views.register('sys-models', { title: () => '模型管理', render: modelsPage });
  Y7.views.register('sys-runtime', { title: () => '运行与执行槽位', level: 's3', gateText: '执行槽位与排队属于 3.4A。', render: runtimePage });
  Y7.views.register('sys-tools', { title: () => '工具与扩展', level: 's3', gateText: '网络、MCP 工具与扩展接口属于 3.2B 与 3.7。', render: toolsPage });
  Y7.views.register('sys-meta', { title: () => '元观察', level: 's5', gateText: '元观察与规则检查部门属于 Stage 5。', render: metaPage });
  Y7.views.register('sys-reserved', { title: (ctx) => (RESERVED[ctx.route.params.which] || { title: '预留入口' }).title, render: reservedPage });

  // ---------------------------------------------------------------------------
  // 界面动作

  const A = Y7.actions.register;

  A('sys.toggleCard', (el) => {
    const id = el.dataset.connectionId;
    st.expanded[id] = !st.expanded[id];
    rerender();
  });

  A('sys.openAdd', () => {
    st.form = { mode: 'add', connectionId: null, scheme: 'opencode-go', protocol: 'messages', name: 'OpenCode Go · Messages', baseUrl: presetBase('opencode-go', 'messages'), credentialRef: 'OPENCODE_GO_KEY', timeoutSec: 120, modelsUrl: '', advancedOpen: false };
    rerender();
    document.getElementById('y7-conn-form').scrollIntoView({ block: 'start' });
  });

  A('sys.openEdit', (el) => {
    const conn = Y7.model.connection(el.dataset.connectionId);
    st.form = { mode: 'edit', connectionId: conn.id, scheme: conn.scheme, protocol: conn.protocol, name: conn.name, baseUrl: conn.baseUrl, credentialRef: conn.credentialRef, timeoutSec: conn.timeoutSec, modelsUrl: conn.modelsUrl, advancedOpen: Boolean(conn.modelsUrl) };
    rerender();
    document.getElementById('y7-conn-form').scrollIntoView({ block: 'start' });
  });

  A('sys.cancelForm', () => {
    st.form = null;
    rerender();
  });

  A('sys.formScheme', (el) => {
    const f = st.form;
    f.scheme = el.dataset.scheme;
    if (f.scheme === 'custom') {
      if (f.mode === 'add') f.baseUrl = '';
    } else {
      const sch = scheme(f.scheme);
      if (!sch.protocols.some((item) => item.protocol === f.protocol)) f.protocol = sch.protocols[0].protocol;
      f.baseUrl = presetBase(f.scheme, f.protocol);
    }
    rerender();
  });

  A('sys.formProtocol', (el) => {
    const f = st.form;
    f.protocol = el.value;
    if (f.scheme !== 'custom') f.baseUrl = presetBase(f.scheme, f.protocol);
    rerender();
  });

  A('sys.formField', (el) => {
    const key = el.dataset.field;
    st.form[key] = key === 'timeoutSec' ? Number(el.value) : el.value;
  });

  function formParams() {
    const f = st.form;
    return { mode: f.mode, connectionId: f.connectionId, name: f.name, scheme: f.scheme, protocol: f.protocol, baseUrl: f.baseUrl, credentialRef: f.credentialRef || '', timeoutSec: String(f.timeoutSec), modelsUrl: f.modelsUrl || '' };
  }

  A('sys.saveForm', () => {
    const f = st.form;
    const original = f.mode === 'edit' ? Y7.model.connection(f.connectionId) : null;
    const changes = original ? invalidatingChanges(original, f) : [];
    const admitted = original ? catalogRaw().definitions.filter((def) => def.connectionId === original.id && def.admission).map((def) => def.id) : [];
    if (changes.length && admitted.length) {
      Y7.ui.modal({
        title: '保存会作废准入',
        body: impactHtml(admitted, '修改了' + changes.join('、') + '：该连接下全部定义回到候选。'),
        actions: [{ label: '取消', close: true }, { label: '确认保存', kind: 'danger', act: 'sys.confirmSaveForm' }]
      });
      return;
    }
    const result = Y7.command('saveConnection', formParams());
    if (result.ok) {
      st.form = null;
      st.expanded[result.connectionId] = true;
      rerender();
    }
  });

  A('sys.confirmSaveForm', () => {
    const result = Y7.command('saveConnection', Object.assign(formParams(), { confirmed: 'yes' }));
    Y7.ui.closeModal();
    if (result.ok) {
      st.form = null;
      rerender();
    }
  });

  A('sys.deleteConnection', (el) => {
    const id = el.dataset.connectionId;
    const defs = catalogRaw().definitions.filter((def) => def.connectionId === id).map((def) => def.id);
    const refs = referrersOf(defs);
    const conn = Y7.model.connection(id);
    if (refs.length) {
      Y7.ui.modal({
        title: '不能删除「' + conn.name + '」',
        body: '<p>这份 Provider 配置下的定义仍被引用，删除被拒绝。先修改下列引用方：</p><ul class="y7-list">' + refs.map((ref) => '<li>' + esc(ref.text) + ' → ' + esc(Y7.model.label(ref.definition)) + '</li>').join('') + '</ul>',
        actions: [{ label: '知道了', kind: 'primary', close: true }]
      });
      return;
    }
    Y7.ui.modal({
      title: '删除「' + conn.name + '」',
      body: '<p>确认后连同下列模型访问定义一起删除：</p>' + (defs.length ? '<ul class="y7-list">' + defs.map((d) => '<li>' + esc(Y7.model.label(d)) + '</li>').join('') + '</ul>' : '<p class="y7-muted">没有模型访问定义</p>'),
      actions: [{ label: '取消', close: true }, { label: '删除', kind: 'danger', cmd: 'deleteConnection', close: true, data: { connectionId: id, confirmed: 'yes' } }]
    });
  });

  A('sys.addCandidate', (el) => {
    Y7.command('addCandidate', { connectionId: el.dataset.connectionId, model: el.dataset.model });
  });

  A('sys.editDefinition', (el) => {
    const def = Y7.model.definition(el.dataset.definitionId);
    const r = def.reasoning || { levels: [], defaultLevel: null, method: 'effort' };
    const checks = Y7.REASONING_LEVELS.map((level) => '<label class="y7-check"><input type="checkbox" name="y7-def-level" value="' + level + '"' + (r.levels.includes(level) ? ' checked' : '') + '> ' + level + '</label>').join('');
    Y7.ui.modal({
      title: '修改模型访问定义 · ' + def.upstreamModel,
      body: '<div class="y7-form"><div class="y7-grid-2">' +
        '<label class="y7-field"><span>窗口</span><input class="y7-input" type="number" id="y7-def-window" min="1" value="' + esc(def.window || '') + '"></label>' +
        '<label class="y7-field"><span>输出上限</span><input class="y7-input" type="number" id="y7-def-max" min="1" value="' + esc(def.maxOutput || '') + '"></label></div>' +
        '<fieldset class="y7-field"><legend>支持档位（只包含上游接受的取值；不选表示未声明）</legend><div class="y7-check-row">' + checks + '</div></fieldset>' +
        '<div class="y7-grid-2"><label class="y7-field"><span>默认档位</span><select class="y7-select" id="y7-def-default">' + Y7.REASONING_LEVELS.map((level) => '<option value="' + level + '"' + (level === r.defaultLevel ? ' selected' : '') + '>' + level + '</option>').join('') + '</select></label>' +
        '<label class="y7-field"><span>推理参数方式</span><select class="y7-select" id="y7-def-method">' + METHODS.map((m) => '<option value="' + m + '"' + (m === r.method ? ' selected' : '') + '>' + m + '</option>').join('') + '</select><small class="y7-muted">修改推理参数方式会作废准入；窗口、输出上限与档位的修改保持准入</small></label></div>' +
        '<p class="y7-muted y7-small">修改窗口或输出上限等同于确认容量。</p><div id="y7-def-error"></div></div>',
      actions: [{ label: '取消', close: true }, { label: '保存', kind: 'primary', act: 'sys.saveDefinition', data: { definitionId: def.id } }]
    });
  });

  function definitionParams(id) {
    const levels = Array.from(document.querySelectorAll('input[name="y7-def-level"]:checked')).map((input) => input.value);
    return {
      definitionId: id,
      window: document.getElementById('y7-def-window').value,
      maxOutput: document.getElementById('y7-def-max').value,
      levels: levels.join(','),
      defaultLevel: document.getElementById('y7-def-default').value,
      method: document.getElementById('y7-def-method').value
    };
  }

  A('sys.saveDefinition', (el) => {
    const params = definitionParams(el.dataset.definitionId);
    const def = Y7.model.definition(params.definitionId);
    const oldMethod = def.reasoning ? def.reasoning.method : null;
    const newMethod = params.levels ? params.method : null;
    const methodChanged = Boolean(def.admission) && oldMethod !== newMethod;
    if (methodChanged && el.dataset.confirmed !== 'yes') {
      document.getElementById('y7-def-error').innerHTML = '<div class="y7-json-errors is-warn">' + impactHtml([def.id], '修改推理参数方式：这个定义回到候选。') + '</div>';
      el.dataset.confirmed = 'yes';
      el.querySelector('span').textContent = '确认保存（作废准入）';
      el.classList.add('danger');
      return;
    }
    const result = Y7.command('saveDefinition', Object.assign(params, { confirmed: el.dataset.confirmed || '' }));
    if (result.ok) Y7.ui.closeModal();
    else document.getElementById('y7-def-error').innerHTML = ui.note(esc(result.message), 'warn');
  });

  A('sys.removeDefinition', (el) => {
    const id = el.dataset.definitionId;
    const refs = referrersOf([id]);
    if (refs.length) {
      Y7.ui.modal({
        title: '不能移除 ' + Y7.model.label(id),
        body: '<p>这个定义仍被引用，移除被拒绝：</p><ul class="y7-list">' + refs.map((ref) => '<li>' + esc(ref.text) + '</li>').join('') + '</ul>',
        actions: [{ label: '知道了', kind: 'primary', close: true }]
      });
      return;
    }
    Y7.ui.modal({
      title: '移除 ' + Y7.model.label(id),
      body: '<p>没有部门默认或项目部门设置引用它，可以移除。</p>',
      actions: [{ label: '取消', close: true }, { label: '移除', kind: 'danger', cmd: 'removeDefinition', close: true, data: { definitionId: id } }]
    });
  });

  A('sys.credRef', (el) => { st.credRef = el.value; });
  A('sys.credMode', (el) => { st.credMode = el.value; });

  A('sys.saveKey', () => {
    const input = document.getElementById('y7-cred-key');
    const result = Y7.command('saveCredential', { ref: document.getElementById('y7-cred-ref').value, key: input.value, mode: st.credMode });
    input.value = '';
    return result;
  });

  A('sys.clearOverride', () => Y7.command('clearCredentialOverride', { ref: document.getElementById('y7-cred-ref').value }));
  A('sys.removePersisted', () => Y7.command('removePersistedCredential', { ref: document.getElementById('y7-cred-ref').value }));

  function currentDeptDefault(dept) {
    const cat = Y7.resolve(catalogRaw());
    return cat.departmentDefaults[dept] || { definition: null, level: null };
  }

  A('sys.deptModel', (el) => {
    const dept = el.dataset.department;
    const draft = st.deptDraft[dept] || Object.assign({}, currentDeptDefault(dept));
    draft.definition = el.value || null;
    const def = draft.definition ? Y7.model.definition(draft.definition) : null;
    if (!def || !def.reasoning || !def.reasoning.levels.includes(draft.level)) draft.level = null;
    st.deptDraft[dept] = draft;
    rerender();
  });

  A('sys.deptLevel', (el) => {
    const dept = el.dataset.department;
    const draft = st.deptDraft[dept] || Object.assign({}, currentDeptDefault(dept));
    draft.level = el.value || null;
    st.deptDraft[dept] = draft;
    rerender();
  });

  A('sys.saveDept', (el) => {
    const dept = el.dataset.department;
    const draft = st.deptDraft[dept] || currentDeptDefault(dept);
    const result = Y7.command('saveDepartmentDefault', { department: dept, definition: draft.definition || '', level: draft.level || '' });
    if (result.ok) {
      delete st.deptDraft[dept];
      rerender();
    }
  });

  function currentRoleDefault(roleId) {
    return catalogRaw().roleDefaults[roleId] || { definition: null, level: null };
  }

  A('sys.roleModel', (el) => {
    const id = el.dataset.roleId;
    const draft = st.roleDraft[id] || Object.assign({}, currentRoleDefault(id));
    draft.definition = el.value || null;
    const def = draft.definition ? Y7.model.definition(draft.definition) : null;
    if (!def || !def.reasoning || !def.reasoning.levels.includes(draft.level)) draft.level = null;
    st.roleDraft[id] = draft;
    rerender();
  });

  A('sys.roleLevel', (el) => {
    const id = el.dataset.roleId;
    const draft = st.roleDraft[id] || Object.assign({}, currentRoleDefault(id));
    draft.level = el.value || null;
    st.roleDraft[id] = draft;
    rerender();
  });

  A('sys.saveRole', (el) => {
    const id = el.dataset.roleId;
    const draft = st.roleDraft[id] || currentRoleDefault(id);
    const result = Y7.command('saveRoleDefault', { roleId: id, definition: draft.definition || '', level: draft.level || '' });
    if (result.ok) {
      delete st.roleDraft[id];
      rerender();
    }
  });

  A('sys.openJson', () => openJsonModal());

  A('sys.jsonEdit', (el) => {
    st.json.text = el.value;
    if (st.json.confirm) {
      st.json.confirm = null;
      renderJsonModalKeepText();
    }
  });

  function renderJsonModalKeepText() {
    const area = document.getElementById('y7-json-text');
    const pos = area ? area.selectionStart : 0;
    renderJsonModal();
    const next = document.getElementById('y7-json-text');
    next.focus();
    next.setSelectionRange(pos, pos);
  }

  A('sys.jsonFormat', () => {
    const parsed = parseDocument(st.json.text);
    if (parsed.error) {
      st.json.errors = [{ path: '(文档)', message: 'JSON 格式错误：' + parsed.error }];
    } else {
      st.json.text = JSON.stringify(parsed.doc, null, 2);
      st.json.errors = [];
    }
    renderJsonModal();
  });

  A('sys.jsonReset', () => {
    st.json = { text: JSON.stringify(catalogDocument(), null, 2), source: null, errors: [], confirm: null };
    renderJsonModal();
  });

  A('sys.jsonCopy', () => {
    const area = document.getElementById('y7-json-text');
    area.select();
    const copied = document.execCommand('copy');
    area.setSelectionRange(0, 0);
    Y7.ui.toast(copied ? '已复制目录文档' : '浏览器没有允许复制，请手动选择文本复制', copied ? 'ok' : 'warn');
  });

  function readFile(el, then) {
    const file = el.files && el.files[0];
    if (!file) return;
    file.text().then((text) => then(text, file.name));
    el.value = '';
  }

  A('sys.jsonImport', (el) => readFile(el, (text, name) => {
    st.json.text = text;
    st.json.source = name;
    st.json.confirm = null;
    const parsed = parseDocument(text);
    st.json.errors = parsed.error ? [{ path: '(文档)', message: 'JSON 格式错误：' + parsed.error }] : validateDocument(parsed.doc).errors;
    renderJsonModal();
  }));

  A('sys.pageImport', (el) => readFile(el, (text, name) => {
    openJsonModal(text, name);
    const parsed = parseDocument(text);
    st.json.errors = parsed.error ? [{ path: '(文档)', message: 'JSON 格式错误：' + parsed.error }] : validateDocument(parsed.doc).errors;
    renderJsonModal();
  }));

  A('sys.export', () => {
    const result = Y7.command('exportCatalog', {});
    downloadText(result.fileName, result.text);
  });

  A('sys.jsonSave', () => {
    const name = st.json.source ? 'importCatalog' : 'saveCatalogJson';
    const result = Y7.command(name, { text: st.json.text, confirmed: st.json.confirm ? 'yes' : '' });
    if (result.ok) {
      st.json = null;
      Y7.ui.closeModal();
      return;
    }
    st.json.errors = result.errors || [];
    st.json.confirm = result.needsConfirm ? result.invalidations : null;
    renderJsonModalKeepText();
  });

  A('sys.setSlots', () => Y7.command('setSlots', { total: document.getElementById('y7-slot-total').value }));

  // ---------------------------------------------------------------------------
  // 命令

  const C = Y7.commands.register;

  function slugId(name, taken) {
    const base = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'connection';
    let id = base;
    let n = 2;
    while (taken.includes(id)) {
      id = base + '-' + n;
      n += 1;
    }
    return id;
  }

  function revoke(def, reason) {
    def.admissionRevoked = { at: Y7.data.now, reason, previous: def.admission };
    def.admission = null;
  }

  // 保存 Provider 配置
  C('saveConnection', (p) => {
    const name = (p.name || '').trim();
    if (!name) return { ok: false, message: '请填写名称' };
    if (!protocolOptions().includes(p.protocol)) return { ok: false, message: '请选择协议' };
    if (!isUrl(p.baseUrl)) return { ok: false, message: '地址必须是 http:// 或 https:// 开头的请求基址' };
    const timeout = Number(p.timeoutSec);
    if (!Number.isInteger(timeout) || timeout <= 0) return { ok: false, message: '超时必须是正整数' };
    if (p.modelsUrl && !isUrl(p.modelsUrl)) return { ok: false, message: '模型列表地址必须是 http(s) 地址' };
    const credentialRef = p.credentialRef ? p.credentialRef.trim() : null;
    if (credentialRef && !/^[A-Z][A-Z0-9_]*$/.test(credentialRef)) return { ok: false, message: '凭据引用由大写字母、数字与下划线组成' };
    const cat = catalogRaw();
    if (p.mode === 'add') {
      const id = slugId(name, cat.connections.map((conn) => conn.id));
      cat.connections.push({ id, name, scheme: p.scheme, protocol: p.protocol, baseUrl: p.baseUrl, credentialRef, timeoutSec: timeout, modelsUrl: p.modelsUrl || '' });
      cat.connectionTests[id] = null;
      cat.file.revision += 1;
      return { ok: true, message: '已添加 Provider 配置「' + name + '」。获取模型列表后从候选加入模型访问定义', paths: ['catalog.connections'], connectionId: id };
    }
    const conn = Y7.model.connection(p.connectionId);
    if (!conn) throw new Error('找不到 Provider 配置：' + p.connectionId);
    const changes = invalidatingChanges(conn, { baseUrl: p.baseUrl, credentialRef, protocol: p.protocol });
    const affected = cat.definitions.filter((def) => def.connectionId === conn.id && def.admission);
    if (changes.length && affected.length && p.confirmed !== 'yes') {
      return { ok: false, message: '修改' + changes.join('、') + '会作废 ' + affected.length + ' 个定义的准入，需要先确认' };
    }
    Object.assign(conn, { name, scheme: p.scheme, protocol: p.protocol, baseUrl: p.baseUrl, credentialRef, timeoutSec: timeout, modelsUrl: p.modelsUrl || '' });
    if (changes.length) affected.forEach((def) => revoke(def, '连接的' + changes.join('、') + '已修改'));
    cat.file.revision += 1;
    const paths = ['catalog.connections', 'catalog.definitions'].concat(Y7.model.afterChange());
    return { ok: true, message: '已保存「' + name + '」' + (changes.length && affected.length ? '；' + affected.length + ' 个定义回到候选，引用处显示「无法使用：准入已作废」' : '') + '，从下一次模型请求起生效', paths, connectionId: conn.id };
  });

  // 删除 Provider 配置
  C('deleteConnection', (p) => {
    const cat = catalogRaw();
    const conn = Y7.model.connection(p.connectionId);
    if (!conn) throw new Error('找不到 Provider 配置：' + p.connectionId);
    const defs = cat.definitions.filter((def) => def.connectionId === conn.id).map((def) => def.id);
    const refs = referrersOf(defs);
    if (refs.length) return { ok: false, message: '拒绝删除：定义仍被引用（' + refs.map((ref) => ref.text).join('、') + '）' };
    if (p.confirmed !== 'yes') return { ok: false, message: '删除需要确认' };
    cat.connections = cat.connections.filter((item) => item.id !== conn.id);
    cat.definitions = cat.definitions.filter((def) => def.connectionId !== conn.id);
    delete cat.candidates[conn.id];
    delete cat.connectionTests[conn.id];
    cat.file.revision += 1;
    return { ok: true, message: '已删除「' + conn.name + '」及 ' + defs.length + ' 个模型访问定义', paths: ['catalog.connections', 'catalog.definitions'] };
  });

  // 连接测试：只对已保存的连接进行，不改变任何准入
  C('testConnection', (p) => {
    const conn = Y7.model.connection(p.connectionId);
    if (!conn) throw new Error('找不到 Provider 配置：' + p.connectionId);
    let result;
    if (conn.credentialRef) {
      const cred = Y7.model.credential(conn.credentialRef);
      if (!cred || cred.state === 'missing') result = { ok: false, text: '连接测试失败：凭据缺失（' + conn.credentialRef + '）' };
      else if (cred.rejected) result = { ok: false, text: '连接测试失败：HTTP 401，凭据被上游拒绝' };
    }
    if (!result) result = { ok: true, text: conn.protocol === 'decision' ? '连接测试通过 · 判定服务可达 · 96 ms' : '连接测试通过 · ' + (conn.scheme === 'custom' ? 38 : 412) + ' ms' };
    catalogRaw().connectionTests[conn.id] = Object.assign({ at: Y7.data.now }, result);
    return { ok: result.ok, message: conn.name + '：' + result.text, paths: ['catalog.connectionTests'] };
  });

  // 模型测试：一次真实的最小推理请求，通过且容量已确认时写入准入记录
  C('testModel', (p) => {
    const def = Y7.model.definition(p.definitionId);
    if (!def) throw new Error('找不到模型访问定义：' + p.definitionId);
    const conn = Y7.model.connection(def.connectionId);
    if (conn.protocol === 'decision') return { ok: false, message: '决策模型以判定点为单位准入，依靠样本校准' };
    if (!def.capacityAccepted) return { ok: false, message: '先接受或修改容量，再进行模型测试' };
    let failure = null;
    if (conn.credentialRef) {
      const cred = Y7.model.credential(conn.credentialRef);
      if (!cred || cred.state === 'missing') failure = '模型测试失败：凭据缺失（' + conn.credentialRef + '）';
      else if (cred.rejected) failure = '模型测试失败：HTTP 401，凭据被上游拒绝';
    }
    const tests = catalogRaw().modelTests;
    if (failure) {
      tests[def.id] = { at: Y7.data.now, ok: false, text: failure };
      return { ok: false, message: def.upstreamModel + '：' + failure, paths: ['catalog.modelTests'] };
    }
    const level = def.reasoning ? def.reasoning.defaultLevel : null;
    def.admission = { testedAt: Y7.data.now, actualModel: def.upstreamModel, protocol: Y7.PROTOCOL_LABELS[conn.protocol] };
    def.admissionRevoked = null;
    tests[def.id] = { at: Y7.data.now, ok: true, text: '模型测试通过 · 实际返回 ' + def.upstreamModel + (level ? ' · 按默认档位 ' + level + ' 发送推理参数' : ' · 未发送推理参数') };
    const paths = ['catalog.definitions', 'catalog.modelTests'].concat(Y7.model.afterChange());
    return { ok: true, message: def.upstreamModel + '：模型测试通过，已写入准入记录', paths };
  });

  // 获取模型列表：请求该连接生效的模型列表地址，带上凭据
  C('fetchModels', (p) => {
    const cat = catalogRaw();
    const conn = Y7.model.connection(p.connectionId);
    if (!conn) throw new Error('找不到 Provider 配置：' + p.connectionId);
    const source = conn.modelsUrl || scheme(conn.scheme).modelsUrl || null;
    let entry;
    if (!source) entry = { source: null, collectedAt: Y7.data.now, ids: [], unknownReason: '没有模型列表地址' };
    else if (conn.credentialRef && (!Y7.model.credential(conn.credentialRef) || Y7.model.credential(conn.credentialRef).state === 'missing')) entry = { source, collectedAt: Y7.data.now, ids: [], unknownReason: '请求失败：凭据缺失' };
    else if (conn.credentialRef && Y7.model.credential(conn.credentialRef).rejected) entry = { source, collectedAt: Y7.data.now, ids: [], unknownReason: '请求失败：HTTP 401，凭据被上游拒绝' };
    else if (conn.protocol === 'decision') entry = { source, collectedAt: Y7.data.now, ids: ['jev-judge-2', 'jev-judge-3'], unknownReason: null };
    else if (conn.scheme === 'custom') entry = { source, collectedAt: Y7.data.now, ids: ['qwen3-coder-30b', 'llama-3.3-70b-instruct'], unknownReason: null };
    else entry = { source, collectedAt: Y7.data.now, ids: ['kimi-k2.6', 'glm-5', 'mimo-v2.5', 'qwen3.6-plus', 'minimax-m2.7', 'deepseek-v4-flash'], unknownReason: null };
    cat.candidates[conn.id] = entry;
    return { ok: !entry.unknownReason, message: conn.name + '：' + (entry.unknownReason ? '候选未知（' + entry.unknownReason + '），不沿用上一次列表' : '获取到 ' + entry.ids.length + ' 个模型 ID'), paths: ['catalog.candidates'] };
  });

  // 从候选加入模型访问定义表：容量可以预填，接受或修改之前不能保存为可用
  C('addCandidate', (p) => {
    const cat = catalogRaw();
    const id = p.connectionId + '/' + p.model;
    if (cat.definitions.some((def) => def.id === id)) return { ok: false, message: p.model + ' 已在模型访问定义表中' };
    const same = cat.definitions.find((def) => def.upstreamModel === p.model && def.connectionId !== p.connectionId && def.capacityAccepted);
    cat.definitions.push({
      id, connectionId: p.connectionId, upstreamModel: p.model,
      window: same ? same.window : null, maxOutput: same ? same.maxOutput : null,
      reasoning: same && same.reasoning ? Y7.clone(same.reasoning) : null,
      capacityAccepted: false, admission: null, admissionRevoked: null,
      prefill: same ? '预填自 ' + Y7.model.connection(same.connectionId).name + ' 的同名定义，尚未接受' : '没有可以预填的容量，请修改后接受'
    });
    st.expanded[p.connectionId] = true;
    return { ok: true, message: '已加入 ' + p.model + '：' + (same ? '容量已预填，逐行接受或修改' : '请填写窗口与输出上限'), paths: ['catalog.definitions'] };
  });

  // 接受容量
  C('acceptCapacity', (p) => {
    const def = Y7.model.definition(p.definitionId);
    if (!def) throw new Error('找不到模型访问定义：' + p.definitionId);
    if (!def.window || !def.maxOutput) return { ok: false, message: '窗口与输出上限必须有值' };
    if (def.maxOutput > def.window) return { ok: false, message: '输出上限不能大于窗口' };
    def.capacityAccepted = true;
    delete def.prefill;
    return { ok: true, message: def.upstreamModel + '：容量已确认，模型测试通过后准入', paths: ['catalog.definitions'] };
  });

  // 修改模型访问定义
  C('saveDefinition', (p) => {
    const def = Y7.model.definition(p.definitionId);
    if (!def) throw new Error('找不到模型访问定义：' + p.definitionId);
    const windowValue = Number(p.window);
    const maxOutput = Number(p.maxOutput);
    if (!Number.isInteger(windowValue) || windowValue <= 0) return { ok: false, message: '窗口必须是正整数' };
    if (!Number.isInteger(maxOutput) || maxOutput <= 0) return { ok: false, message: '输出上限必须是正整数' };
    if (maxOutput > windowValue) return { ok: false, message: '输出上限不能大于窗口' };
    const levels = p.levels ? String(p.levels).split(',').filter(Boolean) : [];
    if (levels.length && !levels.includes(p.defaultLevel)) return { ok: false, message: '默认档位必须是支持档位之一' };
    if (levels.length && !METHODS.includes(p.method)) return { ok: false, message: '推理参数方式无效' };
    const oldMethod = def.reasoning ? def.reasoning.method : null;
    const newMethod = levels.length ? p.method : null;
    const methodChanged = oldMethod !== newMethod;
    if (methodChanged && def.admission && p.confirmed !== 'yes') return { ok: false, message: '修改推理参数方式会作废准入，需要先确认' };
    const capacityChanged = def.window !== windowValue || def.maxOutput !== maxOutput;
    def.window = windowValue;
    def.maxOutput = maxOutput;
    def.reasoning = levels.length ? { levels: Y7.REASONING_LEVELS.filter((level) => levels.includes(level)), defaultLevel: p.defaultLevel, method: p.method } : null;
    if (capacityChanged) {
      def.capacityAccepted = true;
      delete def.prefill;
    }
    if (methodChanged && def.admission) revoke(def, '推理参数方式由 ' + (oldMethod || '未声明') + ' 改为 ' + (newMethod || '未声明'));
    const paths = ['catalog.definitions'].concat(Y7.model.afterChange());
    return { ok: true, message: def.upstreamModel + '：已保存' + (capacityChanged ? '，容量已确认' : '') + (methodChanged && !def.admission && def.admissionRevoked ? '；准入已作废，需要重新进行模型测试' : '') + '，从下一次模型请求起使用新值', paths };
  });

  // 移除模型访问定义：被引用时拒绝
  C('removeDefinition', (p) => {
    const cat = catalogRaw();
    const def = Y7.model.definition(p.definitionId);
    if (!def) throw new Error('找不到模型访问定义：' + p.definitionId);
    const refs = referrersOf([def.id]);
    if (refs.length) return { ok: false, message: '拒绝移除：仍被引用（' + refs.map((ref) => ref.text).join('、') + '）' };
    cat.definitions = cat.definitions.filter((item) => item.id !== def.id);
    delete cat.modelTests[def.id];
    return { ok: true, message: '已移除 ' + def.upstreamModel, paths: ['catalog.definitions'] };
  });

  // 保存编辑 JSON
  C('saveCatalogJson', (p) => jsonSaveCommand('saveCatalogJson', p));
  // 导入整份目录文档（与编辑 JSON 同一套校验）
  C('importCatalog', (p) => jsonSaveCommand('importCatalog', p));
  // 导出目录文档（不含 API Key、准入记录与项目部门设置）
  C('exportCatalog', () => {
    const text = JSON.stringify(catalogDocument(), null, 2);
    const fileName = 'yudao-catalog-r' + catalogRaw().file.revision + '.json';
    return { ok: true, message: '已导出 ' + fileName + '（不含 API Key、准入记录与项目部门设置）', paths: [], text, fileName };
  });

  // 保存 Key
  C('saveCredential', (p) => {
    const ref = (p.ref || '').trim();
    if (!ref) return { ok: false, message: '请选择凭据引用' };
    if (!p.key || !p.key.trim()) return { ok: false, message: '请输入 API Key' };
    if (!['memory', 'dotenv'].includes(p.mode)) throw new Error('未知写入方式：' + p.mode);
    const list = catalogRaw().credentials;
    let cred = list.find((item) => item.ref === ref);
    if (!cred) {
      cred = { ref, state: 'missing', sources: { memory: false, env: false, dotenv: false }, version: null, rejected: false, rejectedSource: null, note: '' };
      list.push(cred);
    }
    cred.sources[p.mode] = true;
    if (cred.rejectedSource === p.mode) cred.rejectedSource = null;
    cred.version = bumpVersion(cred.version);
    recomputeCredential(cred);
    const paths = ['catalog.credentials'].concat(Y7.model.afterChange());
    return { ok: true, message: ref + '：Key 已保存（' + (p.mode === 'memory' ? '只在本进程有效，重启后需重新提供' : '写入 .yudao/.env') + '），版本 ' + cred.version + '，从下一次模型请求起生效', paths };
  });

  // 清除内存覆盖
  C('clearCredentialOverride', (p) => {
    const cred = Y7.model.credential(p.ref);
    if (!cred) throw new Error('找不到凭据：' + p.ref);
    if (!cred.sources.memory) return { ok: false, message: p.ref + '：没有内存覆盖' };
    cred.sources.memory = false;
    recomputeCredential(cred);
    const paths = ['catalog.credentials'].concat(Y7.model.afterChange());
    return { ok: true, message: p.ref + '：已清除内存覆盖，现在使用' + (cred.state === 'missing' ? '——凭据缺失' : '「' + CRED_LABELS[cred.state] + '」来源'), paths };
  });

  // 删除持久凭据
  C('removePersistedCredential', (p) => {
    const cred = Y7.model.credential(p.ref);
    if (!cred) throw new Error('找不到凭据：' + p.ref);
    if (!cred.sources.dotenv) return { ok: false, message: p.ref + '：.env 中没有持久凭据' };
    cred.sources.dotenv = false;
    if (cred.rejectedSource === 'dotenv') cred.rejectedSource = null;
    recomputeCredential(cred);
    const paths = ['catalog.credentials'].concat(Y7.model.afterChange());
    return { ok: true, message: p.ref + '：已删除 .yudao/.env 中的持久凭据' + (cred.state === 'missing' ? '，凭据缺失' : ''), paths };
  });

  function checkReference(definition, level) {
    if (!definition) return null;
    const def = Y7.model.definition(definition);
    if (!def) return '没有这个模型访问定义';
    if (!def.admission) return '只能选择已准入的模型访问定义';
    if (level) {
      const levels = def.reasoning ? def.reasoning.levels : [];
      if (!levels.includes(level)) return '请求档位必须属于该模型声明的支持档位';
    }
    return null;
  }

  // 保存部门默认
  C('saveDepartmentDefault', (p) => {
    const dept = p.department;
    if (!deptList().includes(dept)) throw new Error('未知部门：' + dept);
    const definition = p.definition || null;
    const level = p.level || null;
    const problem = checkReference(definition, level);
    if (problem) return { ok: false, message: problem };
    const cat = catalogRaw();
    const value = { definition, level };
    if (dept === 'operations') cat.departmentDefaults.levels.s5.operations = value;
    else cat.departmentDefaults[dept] = value;
    const paths = ['catalog.departmentDefaults'].concat(Y7.model.afterChange());
    return { ok: true, message: '部门默认已保存：' + Y7.deptLabel(dept) + ' · ' + (definition ? Y7.model.label(definition) + (level ? ' · ' + level : '') : '未设置') + '。从各部门下一次模型请求起生效', paths };
  });

  // 保存角色默认（Stage 4）
  C('saveRoleDefault', (p) => {
    const cat = catalogRaw();
    if (!(p.roleId in cat.roleDefaults) || p.roleId === 'level') throw new Error('未知角色：' + p.roleId);
    const definition = p.definition || null;
    const level = p.level || null;
    const problem = checkReference(definition, level);
    if (problem) return { ok: false, message: problem };
    cat.roleDefaults[p.roleId] = { definition, level };
    return { ok: true, message: '角色默认已保存：' + roleName(p.roleId) + ' · ' + (definition ? Y7.model.label(definition) : '未设置（按部门设置）'), paths: ['catalog.roleDefaults'] };
  });

  // 设置执行槽位数
  C('setSlots', (p) => {
    const total = Number(p.total);
    if (!Number.isInteger(total) || total < 1 || total > 8) return { ok: false, message: '执行槽位数必须是 1 到 8 的整数' };
    const used = Y7.runtime.slots().used.length;
    Y7.setEffective(Y7.data.runtime.slots, 'total', total);
    const before = Y7.data.runtime.queue.length;
    const paths = ['runtime.slots'].concat(Y7.runtime.fill());
    const promoted = before - Y7.data.runtime.queue.length;
    return {
      ok: true,
      message: '执行槽位数已设为 ' + total + (total < used ? '；已占用的 ' + used + ' 个事项继续执行，新事项排队' : '') + (promoted ? '；排队中的 ' + promoted + ' 个事项取得执行槽位' : ''),
      paths
    };
  });

  // 取消排队
  C('cancelQueued', (p) => {
    const item = Y7.raw.workItem(p.workItemId);
    if (!item) throw new Error('找不到事项：' + p.workItemId);
    const visible = Y7.workItem(item.id);
    if (!visible || visible.status !== 'queued') return { ok: false, message: '事项不在排队中' };
    const run = Y7.raw.run(item.runId);
    Y7.setWorkItemStatus(item, 'stopped');
    Y7.setEffective(item, 'queuePos', null);
    run.phase = 'FAILED';
    run.stopReason = { code: 'cancelled', text: '用户取消排队' };
    if (run.recovery) {
      run.recovery.state = 'terminated';
      run.recovery.reason = '排队中被取消';
      run.recovery.nextActions = [];
      run.recovery.resumeBlockedReason = '事项已取消';
    }
    const paths = ['workItems[id=' + item.id + ']', 'runs[id=' + run.id + ']'].concat(Y7.runtime.release(item.id));
    return { ok: true, message: '已取消排队：「' + item.title + '」；运行中的事项不受影响', paths };
  });

  // 对置信度不足的判定作出决定
  C('decideJudgment', (p) => {
    const meta = Y7.data.meta;
    const decision = meta.pendingDecisions.find((item) => item.id === p.decisionId);
    if (!decision) throw new Error('找不到等待决定的判定：' + p.decisionId);
    if (!decision.options.includes(p.option)) throw new Error('无效的选项：' + p.option);
    meta.pendingDecisions = meta.pendingDecisions.filter((item) => item.id !== decision.id);
    meta.decisions.push({ id: decision.id, judgmentPointId: decision.judgmentPointId, question: decision.question, option: p.option, at: Y7.data.now });
    return { ok: true, message: '已记录你的决定：「' + p.option + '」，控制层按这个决定处理', paths: ['meta.pendingDecisions', 'meta.decisions'] };
  });
})();
