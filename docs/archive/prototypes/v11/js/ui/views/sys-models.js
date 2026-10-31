// 模型管理页（设计说明第 9.1 节、模型管理设计说明第 9.1 节）
(function () {
  'use strict';
  const Y11 = window.Y11;
  const DEPT_LABELS = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const LEVELS = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
  const METHODS = [['effort', 'effort'], ['adaptive', 'adaptive'], ['budget', 'budget']];
  const CRED_STATE = { memory: '只在本进程有效', env: '宿主进程环境', dotenv: '.yudao/.env', missing: '没有任何来源' };
  const CONN_COMMANDS = [
    'catalog.connection.save', 'catalog.connection.delete', 'catalog.connection.test', 'catalog.model.test',
    'catalog.candidates.collect', 'credential.set', 'credential.clear_override', 'credential.remove_persisted'
  ];

  const st = {
    expanded: Y11.store.get('sys-models.expanded', {}),
    form: null,
    defs: {},
    json: null,
    deptDraft: {},
    roleDraft: {}
  };

  function redraw() { Y11.app.renderContent(true); }
  function cat() { return Y11.api.query('catalog').data; }

  function schemeOf(catalog, id) { return catalog.presets.schemes.find((item) => item.id === id) || null; }
  function presetBase(scheme, protocol) {
    const entry = scheme.protocols.find((item) => item.protocol === protocol);
    return entry ? entry.base_url : '';
  }

  function credentialStatus(conn) {
    if (!conn.credential_ref) return Y11.ui.status('admitted', '无需凭据');
    const cred = conn.credential;
    if (!cred || cred.state === 'missing') return Y11.ui.status('unusable', '凭据缺失');
    return Y11.ui.status(cred.rejected ? 'unusable' : 'admitted', CRED_STATE[cred.state] + (cred.rejected ? ' · 上游拒绝' : ''));
  }

  function referenceStatus(definition, problem) {
    if (!definition) return Y11.ui.status('idle', '未设置');
    if (problem && problem !== '未设置') return Y11.ui.status('unusable', '无法使用：' + problem);
    return Y11.ui.status('admitted', '已准入');
  }

  function warningNote(warning) {
    if (!warning) return '';
    return Y11.ui.note('<strong>建议能力提醒</strong>：' + Y11.esc(warning.text), 'warn');
  }

  // ---------------------------------------------------------------- 目录文件与能力表

  function fileBlock(catalog) {
    const file = catalog.file;
    const body = '<div class="y11-file-row">' +
      Y11.ui.kv([
        ['模型目录文件', Y11.ui.code(file.path)],
        ['目录修订', String(catalog.revision)],
        ['最近重读', Y11.ui.time(file.reloaded_at)],
        ['重读错误', file.reload_error ? Y11.esc(file.reload_error) : '<span class="y11-muted">无</span>']
      ]) +
      Y11.ui.button({ label: '重新读取', kind: 'small', act: 'sm.reload', title: '按当前文件内容重新读取，内容与当前目录一致' }) +
      '</div>';
    return Y11.ui.block({ title: '模型目录文件', query: 'catalog', command: 'catalog.reload', body });
  }

  function capabilityBlock(catalog) {
    const table = catalog.capability_table;
    const rows = Object.keys(table.models).map((id) => ({ id, image: table.models[id].image_input }));
    const body = Y11.ui.table({
      columns: [
        { key: 'id', label: '上游模型', render: (row) => Y11.ui.code(row.id) },
        { key: 'image', label: '支持图像输入', render: (row) => (row.image ? '是' : '否') }
      ],
      rows,
      empty: '能力表没有记录'
    });
    return Y11.ui.block({
      title: '模型能力表', query: 'catalog',
      subtitle: '来源 ' + table.source + ' · 版本 ' + table.revision + '；模型访问定义的「支持图像输入」默认取自能力表，可以手动改写',
      body
    });
  }

  // ---------------------------------------------------------------- Provider 配置卡片

  function candidatesArea(conn) {
    const candidates = conn.candidates;
    if (!candidates) return '<p class="y11-muted">尚未获取模型列表</p>';
    const phase = candidates.phase === 'started' ? Y11.ui.status('running', '测试中') : '';
    const head = '<div class="y11-row"><span class="y11-muted">' + (candidates.source ? '来源 ' + Y11.esc(candidates.source) : '没有模型列表地址') +
      (candidates.collected_at ? ' · 采集于 ' + Y11.ui.time(candidates.collected_at) : '') + '</span>' + phase + '</div>';
    if (candidates.unknown_reason) return head + '<p class="y11-warn-text">候选未知：' + Y11.esc(candidates.unknown_reason) + '</p>';
    const chips = (candidates.prefill || []).map((prefill) => {
      const known = conn.definitions.some((def) => def.upstream_model === prefill.id);
      return '<button type="button" class="y11-chip' + (known ? ' is-done' : '') + '" data-act="sm.addDef" data-connection-id="' + Y11.esc(conn.id) + '" data-candidate="' + Y11.esc(prefill.id) + '">' +
        Y11.esc(prefill.id) + (known ? '<small>已有定义</small>' : '<small>添加</small>') + '</button>';
    }).join('');
    return head + (chips ? '<div class="y11-chip-row">' + chips + '</div>' : '<p class="y11-muted">候选为空</p>');
  }

  function definitionRow(conn, def, index) {
    const accepted = def.capacity_accepted;
    const levels = def.reasoning ? def.reasoning.levels : [];
    const levelBoxes = LEVELS.map((level) =>
      '<label class="y11-check"><input type="checkbox" data-act="sm.defLevel" data-connection-id="' + Y11.esc(conn.id) + '" data-index="' + index + '" data-level="' + level + '" value="' + level + '"' +
      (levels.includes(level) ? ' checked' : '') + '><span>' + level + '</span></label>').join('');
    const defaultOptions = '<option value=""' + (def.reasoning && def.reasoning.default_level ? '' : ' selected') + '>默认档位</option>' +
      levels.map((level) => '<option value="' + level + '"' + (def.reasoning && def.reasoning.default_level === level ? ' selected' : '') + '>' + level + '</option>').join('');
    const methodOptions = METHODS.map((pair) =>
      '<option value="' + pair[0] + '"' + (def.reasoning && def.reasoning.method === pair[1] ? ' selected' : '') + '>' + pair[1] + '</option>').join('');
    const reasoning = '<div class="y11-def-reasoning">' +
      '<div class="y11-check-row">' + levelBoxes + '</div>' +
      '<div class="y11-row"><select class="y11-select" data-act="sm.defDefault" data-connection-id="' + Y11.esc(conn.id) + '" data-index="' + index + '"' + (levels.length ? '' : ' disabled') + '>' + defaultOptions + '</select>' +
      '<select class="y11-select" data-act="sm.defMethod" data-connection-id="' + Y11.esc(conn.id) + '" data-index="' + index + '"' + (levels.length ? '' : ' disabled') + '>' + methodOptions + '</select></div>' +
      (levels.length ? '' : '<small class="y11-muted">取消全部支持档位以后，请求不带推理参数</small>') + '</div>';
    const admission = def.admission
      ? '<div class="y11-cell-stack"><span>' + Y11.ui.status('admitted', '已准入') + '</span><small class="y11-muted">测试于 ' + Y11.ui.time(def.admission.tested_at) + ' · 实际返回 ' + Y11.esc(def.admission.actual_model) + ' · ' + Y11.esc(def.admission.protocol) + '</small></div>'
      : '<div class="y11-cell-stack"><span>' + Y11.ui.status('candidate', '候选') + '</span><small class="y11-muted">' + Y11.esc(def.admission_revoked ? '准入已作废：' + def.admission_revoked.reason : '尚未准入') + '</small></div>';
    const test = cat().model_tests[def.id];
    const testNote = test ? '<small class="y11-test-mini' + (test.ok === false ? ' is-fail' : test.ok ? ' is-ok' : '') + '">' + Y11.esc(test.text) + '</small>' : '';
    const source = (text) => (text ? '<small class="y11-muted">' + Y11.esc(text) + '</small>' : '');
    return '<tr>' +
      '<td data-label="模型访问定义"><div class="y11-cell-stack"><strong>' + Y11.esc(def.upstream_model) + '</strong><small class="y11-muted">' + Y11.ui.code(def.id) + '</small>' + (def.prefill ? '<small class="y11-prefill">' + Y11.esc(def.prefill) + '</small>' : '') + '</div></td>' +
      '<td data-label="窗口"><input class="y11-input" type="number" data-act="sm.defWindow" data-draft="sm-def-' + Y11.esc(def.id) + '-window" data-connection-id="' + Y11.esc(conn.id) + '" data-index="' + index + '" value="' + (def.window === null || def.window === undefined ? '' : def.window) + '">' + source(def.window_source) + '</td>' +
      '<td data-label="输出上限"><input class="y11-input" type="number" data-act="sm.defOutput" data-draft="sm-def-' + Y11.esc(def.id) + '-output" data-connection-id="' + Y11.esc(conn.id) + '" data-index="' + index + '" value="' + (def.max_output === null || def.max_output === undefined ? '' : def.max_output) + '">' + source(def.output_source) + '</td>' +
      '<td data-label="容量"><div class="y11-cell-stack">' +
        (accepted ? '<span>' + Y11.ui.status('admitted', '已接受') + '</span>' : Y11.ui.button({ label: '接受预填', kind: 'small', act: 'sm.defAccept', data: { connectionId: conn.id, index } })) +
        '<small class="y11-muted">接受之前不能保存</small></div></td>' +
      '<td data-label="支持图像输入"><label class="y11-check"><input type="checkbox" data-act="sm.defImage" data-connection-id="' + Y11.esc(conn.id) + '" data-index="' + index + '"' + (def.image_input ? ' checked' : '') + '><span>支持图像输入</span></label>' + source(def.image_input_source) + '</td>' +
      '<td data-label="是否接受要求调用工具"><label class="y11-check"><input type="checkbox" data-act="sm.defAcceptsTool" data-connection-id="' + Y11.esc(conn.id) + '" data-index="' + index + '"' + (def.accepts_required_tool_call ? ' checked' : '') + '><span>接受要求调用工具</span></label></td>' +
      '<td data-label="推理档位声明">' + reasoning + '</td>' +
      '<td data-label="准入">' + admission + '</td>' +
      '<td data-label="操作" class="y11-col-actions"><div class="y11-row">' +
        Y11.ui.button({ label: '模型测试', kind: 'small', act: 'sm.testModel', data: { definitionId: def.id } }) +
        Y11.ui.button({ label: '移除', kind: 'small', act: 'sm.removeDef', data: { connectionId: conn.id, index } }) +
        testNote +
      '</div></td></tr>';
  }

  function connectionCard(conn) {
    const open = Boolean(st.expanded[conn.id]);
    const summary = '<button type="button" class="y11-conn-summary" data-act="sm.toggle" data-connection-id="' + Y11.esc(conn.id) + '" aria-expanded="' + open + '">' +
      '<span class="y11-conn-name"><strong>' + Y11.esc(conn.name) + '</strong><small>' + Y11.esc(conn.scheme === 'custom' ? '自定义' : (schemeOf(cat(), conn.scheme) || { name: conn.scheme }).name) + ' · ' + Y11.esc(conn.protocol) + '</small></span>' +
      '<span class="y11-conn-url">' + Y11.ui.code(conn.base_url) + '</span>' +
      '<span class="y11-conn-cred">' + credentialStatus(conn) + '<small>' + Y11.esc(conn.credential_ref || '无需凭据') + '</small></span>' +
      '<span class="y11-conn-count">已准入 ' + conn.admitted_count + ' · 候选 ' + conn.candidate_count + '</span>' +
      Y11.ui.icon('chevron', 'y11-icon y11-chevron') + '</button>';
    if (!open) return '<article class="y11-conn-card">' + summary + '</article>';
    const test = conn.connection_test;
    const testLine = test
      ? '<span class="y11-test-line">' + (test.phase === 'started' ? Y11.ui.status('running', '测试中') : Y11.ui.status(test.ok ? 'succeeded' : 'failed', test.text)) + '<small>' + Y11.ui.time(test.at) + '</small></span>'
      : '<span class="y11-test-line y11-muted">尚未做连接测试</span>';
    const defs = st.defs[conn.id] || conn.definitions;
    const table = defs.length
      ? '<div class="y11-table-wrap"><table class="y11-table y11-table-defs"><thead><tr>' +
        ['模型访问定义', '窗口', '输出上限', '容量', '支持图像输入', '是否接受要求调用工具', '推理档位声明', '准入', '操作']
          .map((label) => '<th>' + label + '</th>').join('') +
        '</tr></thead><tbody>' + defs.map((def, index) => definitionRow(conn, def, index)).join('') + '</tbody></table></div>'
      : Y11.ui.empty('没有模型访问定义');
    const draft = Boolean(st.defs[conn.id]);
    const body =
      '<div class="y11-row"><span class="y11-muted">模型列表地址：' + Y11.esc(conn.models_url || '用服务方案的地址') + ' · 超时 ' + conn.timeout_sec + ' 秒</span></div>' +
      '<div class="y11-row">' +
        Y11.ui.button({ label: '编辑配置', kind: 'small', act: 'sm.edit', data: { connectionId: conn.id } }) +
        Y11.ui.button({ label: '测试连接', kind: 'small', act: 'sm.testConnection', data: { connectionId: conn.id }, title: '只测试已保存的连接' }) +
        Y11.ui.button({ label: '获取模型列表', kind: 'small', act: 'sm.collect', data: { connectionId: conn.id } }) +
        Y11.ui.button({ label: '删除配置', kind: 'small danger', act: 'sm.deleteConnection', data: { connectionId: conn.id } }) +
        (draft ? Y11.ui.button({ label: '保存定义', kind: 'small primary', act: 'sm.saveDefs', data: { connectionId: conn.id } }) : '') +
      '</div>' + testLine +
      '<h3 class="y11-h3">候选</h3>' + candidatesArea(conn) +
      '<h3 class="y11-h3">模型访问定义</h3>' + table;
    return '<article class="y11-conn-card is-open">' + summary + '<div class="y11-conn-body">' + body + '</div></article>';
  }

  function connectionsBlock(catalog) {
    const cards = catalog.connections.map(connectionCard).join('');
    return Y11.ui.block({
      title: 'Provider 配置', query: 'catalog', command: CONN_COMMANDS,
      subtitle: '一份配置只声明一种协议；模型的窗口与输出上限在接受之前不能保存',
      actions: Y11.ui.button({ label: '添加 Provider 配置', kind: 'small primary', act: 'sm.add' }),
      body: '<div class="y11-conn-list">' + cards + '</div>'
    });
  }

  // ---------------------------------------------------------------- 添加与编辑表单

  function currentForm() {
    const f = st.form;
    const catalog = cat();
    const scheme = schemeOf(catalog, f.scheme);
    const schemeButtons = catalog.presets.schemes.map((item) =>
      '<button type="button" class="y11-pill' + (item.id === f.scheme ? ' is-on' : '') + '" data-act="sm.formScheme" data-scheme="' + Y11.esc(item.id) + '">' + Y11.esc(item.name) + '</button>').join('');
    const schemeInfo = '<p class="y11-small">预置表修订 ' + Y11.esc(catalog.presets.revision) + ' · 来源 ' + Y11.esc(catalog.presets.source) + '</p>' +
      '<p class="y11-small">认证 ' + Y11.esc(scheme.auth) + (scheme.headers.length ? ' · 必需请求头 ' + Y11.esc(scheme.headers.join('、')) : '') + '</p>' +
      (scheme.docs_url ? '<p class="y11-small">文档 ' + Y11.ui.code(scheme.docs_url) + '</p>' : '') +
      (scheme.models_url ? '<p class="y11-small">模型列表地址 ' + Y11.ui.code(scheme.models_url) + '</p>' : '') +
      '<p class="y11-small">模型能力表修订 ' + Y11.esc(catalog.capability_table.revision) + ' · 来源 ' + Y11.esc(catalog.capability_table.source) + '</p>';
    const protocolOptions = ['responses', 'chat', 'messages'].map((p) => {
      const labels = { responses: 'Responses', chat: 'Chat Completions', messages: 'Anthropic Messages' };
      return '<option value="' + p + '"' + (f.protocol === p ? ' selected' : '') + '>' + labels[p] + '</option>';
    }).join('');
    const refs = catalog.credentials.map((cred) => cred.ref).join('、');
    const original = f.connectionId ? catalog.connections.find((item) => item.id === f.connectionId) : null;
    const changes = [];
    if (original) {
      if ((original.base_url || '') !== (f.base_url || '')) changes.push('地址');
      if ((original.credential_ref || '') !== (f.credential_ref || '')) changes.push('凭据引用');
      if (original.protocol !== f.protocol) changes.push('协议');
    }
    const body = '<div class="y11-form">' +
      '<div class="y11-field"><span>服务方案</span><div class="y11-pill-row">' + schemeButtons + '</div>' + schemeInfo + '</div>' +
      '<label class="y11-field"><span>名称</span><input class="y11-input" type="text" data-draft="sm-form-name" data-act="sm.formField" data-field="name" value="' + Y11.esc(f.name) + '"></label>' +
      '<label class="y11-field"><span>协议</span><select class="y11-select" data-act="sm.formProtocol">' + protocolOptions + '</select></label>' +
      '<label class="y11-field"><span>请求基址</span><input class="y11-input" type="text" data-draft="sm-form-base" data-act="sm.formField" data-field="base_url" value="' + Y11.esc(f.base_url) + '"' + (f.scheme === 'custom' ? '' : ' readonly') + '><small class="y11-muted">选择协议以后取该方案该协议的请求基址；自定义方案自行填写</small></label>' +
      '<label class="y11-field"><span>凭据引用</span><input class="y11-input" type="text" data-draft="sm-form-cred" data-act="sm.formField" data-field="credential_ref" value="' + Y11.esc(f.credential_ref || '') + '" list="y11-cred-refs"><datalist id="y11-cred-refs">' + catalog.credentials.map((cred) => '<option value="' + Y11.esc(cred.ref) + '"></option>').join('') + '</datalist><small class="y11-muted">已有引用：' + Y11.esc(refs || '无') + '；Key 在凭据区填写，不写进这里</small></label>' +
      '<details class="y11-details"' + (f.advancedOpen || f.models_url ? ' open' : '') + '><summary>高级选项</summary><div class="y11-form">' +
        '<label class="y11-field"><span>超时（秒）</span><input class="y11-input" type="number" data-draft="sm-form-timeout" data-act="sm.formField" data-field="timeout_sec" value="' + f.timeout_sec + '"></label>' +
        '<label class="y11-field"><span>模型列表地址</span><input class="y11-input" type="text" data-draft="sm-form-models" data-act="sm.formField" data-field="models_url" value="' + Y11.esc(f.models_url || '') + '"><small class="y11-muted">留空时使用服务方案的地址</small></label>' +
      '</div></details>' +
      (changes.length && (original.admitted_count || original.candidate_count)
        ? Y11.ui.note('保存会修改 <strong>' + changes.join('、') + '</strong>：该配置下已准入的定义回到候选，引用保留并显示「无法使用：准入已作废」，从下一次模型请求起影响进行中的事项。', 'warn')
        : '') +
      (f.connectionId
        ? '<p class="y11-muted y11-small">模型访问定义在展开的卡片中编辑。</p>'
        : '<div class="y11-field"><span>模型访问定义</span>' + Y11.ui.empty('打开时模型访问定义表为空。保存后展开卡片获取模型列表，点击候选加入。') + '</div>') +
      '<div class="y11-row">' +
        Y11.ui.button({ label: f.connectionId ? '保存 Provider 配置' : '添加 Provider 配置', kind: 'primary', act: 'sm.saveConnection' }) +
        Y11.ui.button({ label: '取消', act: 'sm.cancelForm' }) +
      '</div></div>';
    return Y11.ui.block({
      id: 'y11-conn-form', title: f.connectionId ? '编辑 Provider 配置' : '添加 Provider 配置',
      className: 'y11-form-block', query: 'catalog', command: 'catalog.connection.save', body
    });
  }

  // ---------------------------------------------------------------- 凭据

  function credentialsBlock(catalog) {
    const refs = catalog.credentials.map((cred) => cred.ref);
    catalog.connections.forEach((conn) => { if (conn.credential_ref && !refs.includes(conn.credential_ref)) refs.push(conn.credential_ref); });
    const rows = refs.map((ref) => {
      const cred = catalog.credentials.find((item) => item.ref === ref);
      return {
        ref,
        state: cred ? CRED_STATE[cred.state] + (cred.rejected ? ' · 上游拒绝' : '') : '没有任何来源',
        version: cred ? cred.version : '—',
        note: cred ? cred.note : '连接引用它，还没有写入 Key'
      };
    });
    const table = Y11.ui.table({
      columns: [
        { key: 'ref', label: '凭据引用', render: (row) => Y11.ui.code(row.ref) },
        { key: 'state', label: '状态' },
        { key: 'version', label: '版本' },
        { key: 'note', label: '说明' },
        {
          key: 'act', label: '操作', className: 'y11-col-actions', render: (row) => {
            const cred = catalog.credentials.find((item) => item.ref === row.ref);
            if (!cred) return '<span class="y11-muted">—</span>';
            return '<div class="y11-row">' +
              (cred.sources.memory ? Y11.ui.button({ label: '清除内存覆盖', kind: 'small', act: 'sm.clearOverride', data: { ref: row.ref, baseVersion: cred.version } }) : '') +
              (cred.sources.dotenv ? Y11.ui.button({ label: '删除持久凭据', kind: 'small danger', act: 'sm.removePersisted', data: { ref: row.ref, baseVersion: cred.version } }) : '') +
              '</div>';
          }
        }
      ],
      rows
    });
    const form = '<div class="y11-cred-form"><h3 class="y11-h3">写入凭据</h3>' +
      '<label class="y11-field"><span>凭据引用</span><input class="y11-input" type="text" id="y11-cred-ref" value="' + Y11.esc(refs[0] || '') + '" list="y11-cred-refs-form"><datalist id="y11-cred-refs-form">' + refs.map((ref) => '<option value="' + Y11.esc(ref) + '"></option>').join('') + '</datalist></label>' +
      '<label class="y11-field"><span>API Key</span><input class="y11-input" type="password" id="y11-cred-key" value="" autocomplete="off"><small class="y11-muted">Key 不回填，也不进入事件</small></label>' +
      '<fieldset class="y11-field"><legend>写入方式</legend><div class="y11-radio-row">' +
        '<label><input type="radio" name="y11-cred-persist" value="memory" checked><span>只在本进程有效</span></label>' +
        '<label><input type="radio" name="y11-cred-persist" value="dotenv"><span>写入 .env</span></label>' +
      '</div></fieldset>' +
      Y11.ui.button({ label: '保存凭据', kind: 'primary', act: 'sm.saveCred' }) + '</div>';
    return Y11.ui.block({
      title: '凭据', query: 'catalog', command: ['credential.set', 'credential.clear_override', 'credential.remove_persisted'],
      subtitle: 'Key 只写入内存或 .yudao/.env，不进入界面数据、事件与提交',
      body: '<div class="y11-grid-cred"><div>' + table + '</div>' + form + '</div>'
    });
  }

  // ---------------------------------------------------------------- 目录文档

  function documentBlock(catalog) {
    const body = Y11.ui.kv([
      ['文档内容', '连接、模型访问定义、部门默认与角色默认'],
      ['不含', 'API Key、准入记录、项目部门设置与项目角色设置']
    ]);
    return Y11.ui.block({
      title: '目录文档（编辑 JSON）', query: 'catalog.document', command: 'catalog.document.save',
      actions: Y11.ui.button({ label: '编辑 JSON', kind: 'small', act: 'sm.jsonOpen' }),
      body
    });
  }

  function jsonBody() {
    const j = st.json;
    const errors = j.errors.length
      ? '<div class="y11-json-errors" role="alert"><strong>整份拒绝，没有写入任何内容</strong><ul>' + j.errors.map((e) => '<li><code>' + Y11.esc(e.path) + '</code>' + Y11.esc(e.message) + '</li>').join('') + '</ul></div>'
      : '';
    const source = j.source ? '<p class="y11-muted">来源：' + Y11.esc(j.source) + '</p>' : '';
    return errors + source +
      '<textarea class="y11-textarea y11-json" id="y11-json-text" spellcheck="false">' + Y11.esc(j.text) + '</textarea>' +
      '<div class="y11-row"><span class="y11-muted">修订 ' + Y11.esc(String(j.revision)) + '</span></div>';
  }

  function jsonActions() {
    return [
      { label: '格式化', act: 'sm.jsonFormat' },
      { label: '重置', act: 'sm.jsonReset', title: '回到当前目录内容' },
      { label: '复制', act: 'sm.jsonCopy' },
      { label: '导入文件', act: 'sm.jsonImport' },
      { label: '导出文件', act: 'sm.jsonExport' },
      { label: '保存', kind: 'primary', act: 'sm.jsonSave' },
      { label: '关闭', close: true }
    ];
  }

  function renderJsonModal() {
    Y11.ui.modal({ title: '目录文档', wide: true, body: jsonBody() + '<input type="file" id="y11-json-file" accept="application/json,.json" hidden data-act="sm.jsonFile">', actions: jsonActions() });
  }

  function openJson(text, source) {
    const doc = Y11.api.query('catalog.document').data;
    st.json = { text: text === undefined ? JSON.stringify(doc.document, null, 2) : text, source: source || null, errors: [], revision: doc.revision };
    renderJsonModal();
  }

  // ---------------------------------------------------------------- 部门默认与角色默认

  function modelOptions(catalog, selected, placeholder) {
    const orphan = selected && !catalog.admitted.some((def) => def.id === selected)
      ? '<option value="' + Y11.esc(selected) + '" selected>' + Y11.esc(selected) + '（无法使用）</option>'
      : '';
    const groups = catalog.connections.map((conn) => {
      const defs = catalog.admitted.filter((def) => def.connection_id === conn.id);
      if (!defs.length) return '';
      return '<optgroup label="' + Y11.esc(conn.name) + '">' + defs.map((def) =>
        '<option value="' + Y11.esc(def.id) + '"' + (def.id === selected ? ' selected' : '') + '>' + Y11.esc(def.upstream_model) + (def.image_input ? '' : '（无图像输入）') + '</option>').join('') + '</optgroup>';
    }).join('');
    return '<option value=""' + (selected ? '' : ' selected') + '>' + Y11.esc(placeholder) + '</option>' + orphan + groups;
  }

  function levelOptions(definitionId, selected, attrs) {
    const catalog = cat();
    const attribute = attrs ? ' ' + attrs : '';
    if (!definitionId) return { html: '<select class="y11-select"' + attribute + ' disabled><option>先选择模型</option></select>', note: '<small class="y11-muted">先选择模型</small>' };
    const entry = catalog.connections.reduce((found, conn) => found || conn.definitions.find((item) => item.id === definitionId), null);
    const list = entry && entry.reasoning ? entry.reasoning.levels : [];
    if (!list.length) return { html: '<select class="y11-select"' + attribute + ' disabled><option>—</option></select>', note: '<small class="y11-muted">该模型未声明推理档位，请求不带推理参数</small>' };
    const options = '<option value=""' + (selected ? '' : ' selected') + '>跟随模型默认' + (entry.reasoning.default_level ? '（' + entry.reasoning.default_level + '）' : '') + '</option>' +
      list.map((level) => '<option value="' + level + '"' + (level === selected ? ' selected' : '') + '>' + level + '</option>').join('');
    return { html: '<select class="y11-select"' + attribute + '>' + options + '</select>', note: '<small class="y11-muted">支持 ' + list.join('、') + '</small>' };
  }

  function departmentBlock(catalog) {
    const depts = Object.keys(catalog.department_defaults);
    const cards = depts.map((dept) => {
      const saved = catalog.department_defaults[dept];
      const draft = st.deptDraft[dept] || { definition: saved.definition, request_level: saved.request_level };
      const level = levelOptions(draft.definition, draft.request_level, 'data-act="sm.deptLevel" data-department="' + Y11.esc(dept) + '"');
      return '<article class="y11-dept-card' + (dept === 'operations' ? ' is-ops' : '') + '">' +
        '<header><h3>' + Y11.esc(DEPT_LABELS[dept]) + (dept === 'operations' ? Y11.ui.tag('Stage 4') : '') + '</h3>' + referenceStatus(saved.definition, saved.problem) + '</header>' +
        '<div class="y11-dept-current"><span class="y11-muted">当前</span><strong>' + Y11.esc(saved.label) + '</strong>' + (saved.request_level ? '<span class="y11-level is-default">' + Y11.esc(saved.request_level) + '</span>' : '') + '</div>' +
        (saved.warning ? warningNote(saved.warning) : '') +
        '<label class="y11-field"><span>模型</span><select class="y11-select" data-act="sm.deptModel" data-department="' + Y11.esc(dept) + '">' + modelOptions(catalog, draft.definition, '未设置') + '</select></label>' +
        '<label class="y11-field"><span>推理档位</span>' + level.html + level.note + '</label>' +
        Y11.ui.button({ label: '保存', kind: 'small primary', act: 'sm.saveDept', data: { department: dept } }) +
        '</article>';
    }).join('');
    return Y11.ui.block({
      title: '部门默认', query: 'catalog', command: 'catalog.department_defaults.save',
      subtitle: '从各部门下一次模型请求起生效，没有另选模型的项目同样生效，包括进行中的事项；全局只有一份，所有项目共用',
      body: '<div class="y11-dept-grid">' + cards + '</div>'
    });
  }

  function roleBlock(catalog) {
    if (!catalog.role_defaults || !catalog.role_catalog) return '';
    const sections = Object.keys(catalog.role_catalog).map((dept) => {
      const rows = catalog.role_catalog[dept].map((role) => {
        const saved = catalog.role_defaults[role.id] || { definition: null, request_level: null, label: '未设置', problem: '未设置', warning: null };
        const draft = st.roleDraft[role.id] || { definition: saved.definition, request_level: saved.request_level };
        const level = levelOptions(draft.definition, draft.request_level, 'data-act="sm.roleLevel" data-role-id="' + Y11.esc(role.id) + '"');
        return {
          id: role.id,
          name: role.name,
          duty: role.duty,
          current: '<div class="y11-cell-stack"><span>' + Y11.esc(saved.label) + '</span>' + referenceStatus(saved.definition, saved.problem) + (saved.warning ? '<small class="y11-warn-text">' + Y11.esc(saved.warning.text) + '</small>' : '') + '</div>',
          model: '<select class="y11-select" data-act="sm.roleModel" data-role-id="' + Y11.esc(role.id) + '">' + modelOptions(catalog, draft.definition, '跟随部门默认') + '</select>',
          level: level.html + level.note,
          act: Y11.ui.button({ label: '保存', kind: 'small', act: 'sm.saveRole', data: { roleId: role.id } })
        };
      });
      return '<section class="y11-role-section"><h3 class="y11-h3">' + Y11.esc(DEPT_LABELS[dept]) + '部门</h3>' + Y11.ui.table({
        columns: [
          { key: 'name', label: '角色', render: (row) => '<div class="y11-cell-stack"><strong>' + Y11.esc(row.name) + '</strong><small class="y11-muted">' + Y11.esc(row.duty) + '</small></div>' },
          { key: 'current', label: '当前', render: (row) => row.current },
          { key: 'model', label: '模型', render: (row) => row.model },
          { key: 'level', label: '推理档位', render: (row) => row.level },
          { key: 'act', label: '操作', className: 'y11-col-actions', render: (row) => row.act }
        ], rows
      }) + '</section>';
    }).join('');
    return Y11.ui.block({
      title: '角色默认', query: 'catalog', command: 'catalog.role_defaults.save',
      subtitle: '角色默认优先于部门默认；解析顺序：项目角色设置、角色默认、项目部门设置、部门默认，取第一个写入了的',
      body: sections
    });
  }

  // ---------------------------------------------------------------- 页面

  function render() {
    const catalog = cat();
    return '<div class="y11-sys-models">' +
      fileBlock(catalog) +
      connectionsBlock(catalog) +
      (st.form ? currentForm() : '') +
      capabilityBlock(catalog) +
      credentialsBlock(catalog) +
      documentBlock(catalog) +
      departmentBlock(catalog) +
      roleBlock(catalog) +
      '</div>';
  }

  Y11.views.register('sys-models', {
    title: () => '模型管理',
    needs: { queries: ['catalog'], commands: ['catalog.connection.save'] },
    render
  });

  // ---------------------------------------------------------------- 界面动作

  function connOf(id) { return cat().connections.find((item) => item.id === id); }
  function defList(conn, index) {
    if (!st.defs[conn.id]) st.defs[conn.id] = Y11.clone(conn.definitions);
    const list = st.defs[conn.id];
    const def = list[index];
    if (!def) throw new Error('没有这个模型访问定义：' + conn.id + ' #' + index);
    return { list, def };
  }

  Y11.actions.register('sm.toggle', (el) => {
    const id = el.dataset.connectionId;
    st.expanded[id] = !st.expanded[id];
    Y11.store.set('sys-models.expanded', st.expanded);
    redraw();
  });

  Y11.actions.register('sm.reload', () => { Y11.run('catalog.reload', {}); redraw(); });

  Y11.actions.register('sm.add', () => {
    st.form = { connectionId: null, scheme: 'opencode-go', protocol: 'responses', name: 'OpenCode Go · Responses', base_url: presetBase(schemeOf(cat(), 'opencode-go'), 'responses'), credential_ref: 'OPENCODE_GO_KEY', timeout_sec: 120, models_url: '', advancedOpen: false };
    redraw();
    const form = document.getElementById('y11-conn-form');
    if (form) form.scrollIntoView({ block: 'start' });
  });

  Y11.actions.register('sm.edit', (el) => {
    const conn = connOf(el.dataset.connectionId);
    st.form = { connectionId: conn.id, scheme: conn.scheme, protocol: conn.protocol, name: conn.name, base_url: conn.base_url, credential_ref: conn.credential_ref || '', timeout_sec: conn.timeout_sec, models_url: conn.models_url || '', advancedOpen: Boolean(conn.models_url) };
    redraw();
    const form = document.getElementById('y11-conn-form');
    if (form) form.scrollIntoView({ block: 'start' });
  });

  Y11.actions.register('sm.cancelForm', () => { st.form = null; redraw(); });

  Y11.actions.register('sm.formField', (el) => {
    const f = st.form;
    if (!f) return;
    f[el.dataset.field] = el.value;
    if (el.dataset.field === 'models_url') f.advancedOpen = Boolean(el.value);
  });

  Y11.actions.register('sm.formScheme', (el) => {
    const f = st.form;
    const scheme = schemeOf(cat(), el.dataset.scheme);
    f.scheme = scheme.id;
    if (scheme.protocols.length) {
      if (!scheme.protocols.some((item) => item.protocol === f.protocol)) f.protocol = scheme.protocols[0].protocol;
      f.base_url = presetBase(scheme, f.protocol);
    }
    redraw();
  });

  Y11.actions.register('sm.formProtocol', (el) => {
    const f = st.form;
    f.protocol = el.value;
    const scheme = schemeOf(cat(), f.scheme);
    if (scheme.protocols.length) f.base_url = presetBase(scheme, f.protocol);
    redraw();
  });

  function defPayload(def) {
    return {
      id: def.id,
      upstream_model: def.upstream_model,
      window: def.window,
      max_output: def.max_output,
      image_input: Boolean(def.image_input),
      accepts_required_tool_call: Boolean(def.accepts_required_tool_call),
      reasoning: def.reasoning ? { levels: def.reasoning.levels.slice(), default_level: def.reasoning.default_level, method: def.reasoning.method } : null,
      capacity_accepted: Boolean(def.capacity_accepted)
    };
  }

  function formParams() {
    const f = st.form;
    const params = {
      name: f.name, scheme: f.scheme, protocol: f.protocol, base_url: f.base_url,
      credential_ref: f.credential_ref, timeout_sec: Number(f.timeout_sec), models_url: f.models_url || '',
      base_version: cat().revision
    };
    if (f.connectionId) params.connection_id = f.connectionId;
    if (f.connectionId && st.defs[f.connectionId]) params.definitions = st.defs[f.connectionId].map(defPayload);
    return params;
  }

  Y11.actions.register('sm.saveConnection', () => {
    const result = Y11.run('catalog.connection.save', formParams());
    if (!result.accepted) return;
    delete st.defs[st.form.connectionId];
    st.form = null;
    ['sm-form-name', 'sm-form-base', 'sm-form-cred', 'sm-form-timeout', 'sm-form-models'].forEach((key) => Y11.app.clearDraft(key));
    redraw();
  });

  Y11.actions.register('sm.deleteConnection', (el) => {
    const conn = connOf(el.dataset.connectionId);
    const names = conn.definitions.map((def) => def.upstream_model).join('、') || '没有模型访问定义';
    Y11.ui.modal({
      title: '删除「' + conn.name + '」',
      body: '<p>确认后连同下列模型访问定义一起删除：' + Y11.esc(names) + '</p><p class="y11-muted">其下任何定义被引用时删除被拒绝，并列出引用方。</p>',
      actions: [
        { label: '取消', close: true },
        { label: '删除', kind: 'danger', cmd: 'catalog.connection.delete', close: true, data: { connectionId: conn.id, baseVersion: cat().revision } }
      ]
    });
  });

  Y11.actions.register('sm.testConnection', (el) => {
    Y11.run('catalog.connection.test', { connection_id: el.dataset.connectionId });
  });

  Y11.actions.register('sm.collect', (el) => {
    Y11.run('catalog.candidates.collect', { connection_id: el.dataset.connectionId });
  });

  Y11.actions.register('sm.addDef', (el) => {
    const conn = connOf(el.dataset.connectionId);
    const candidates = conn.candidates;
    const prefill = candidates && (candidates.prefill || []).find((item) => item.id === el.dataset.candidate);
    if (!prefill) throw new Error('没有这个候选：' + el.dataset.candidate);
    if (!st.defs[conn.id]) st.defs[conn.id] = Y11.clone(conn.definitions);
    st.defs[conn.id].push({
      id: conn.id + '/' + prefill.id, connection_id: conn.id, upstream_model: prefill.id,
      window: prefill.window, max_output: prefill.max_output,
      image_input: Boolean(prefill.image_input), image_input_source: prefill.image_source,
      accepts_required_tool_call: true,
      reasoning: null, capacity_accepted: false, admission: null, admission_revoked: null,
      prefill: '预填自 ' + (prefill.image_source || '候选'), window_source: prefill.window_source, output_source: prefill.output_source
    });
    redraw();
  });

  Y11.actions.register('sm.defWindow', (el) => {
    const view = defList(connOf(el.dataset.connectionId), Number(el.dataset.index));
    view.def.window = el.value === '' ? null : Number(el.value);
    view.def.capacity_accepted = false;
  });

  Y11.actions.register('sm.defOutput', (el) => {
    const view = defList(connOf(el.dataset.connectionId), Number(el.dataset.index));
    view.def.max_output = el.value === '' ? null : Number(el.value);
    view.def.capacity_accepted = false;
  });

  Y11.actions.register('sm.defAccept', (el) => {
    const view = defList(connOf(el.dataset.connectionId), Number(el.dataset.index));
    const window = Number(view.def.window);
    const output = Number(view.def.max_output);
    if (!Number.isInteger(window) || window <= 0 || !Number.isInteger(output) || output <= 0) {
      Y11.ui.toast('先填写窗口与输出上限，再接受', 'warn');
      return;
    }
    if (output > window) {
      Y11.ui.toast('输出上限不能大于窗口', 'warn');
      return;
    }
    view.def.capacity_accepted = true;
    redraw();
  });

  Y11.actions.register('sm.defImage', (el) => {
    const view = defList(connOf(el.dataset.connectionId), Number(el.dataset.index));
    view.def.image_input = el.checked;
    if (el.checked) view.def.image_input_source = '手动改写';
    redraw();
  });

  Y11.actions.register('sm.defAcceptsTool', (el) => {
    const view = defList(connOf(el.dataset.connectionId), Number(el.dataset.index));
    view.def.accepts_required_tool_call = el.checked;
    redraw();
  });

  Y11.actions.register('sm.defLevel', (el) => {
    const view = defList(connOf(el.dataset.connectionId), Number(el.dataset.index));
    const def = view.def;
    const current = def.reasoning ? def.reasoning.levels.slice() : [];
    const level = el.dataset.level;
    const next = el.checked ? current.concat([level]) : current.filter((item) => item !== level);
    if (!next.length) {
      def.reasoning = null;
    } else {
      const ordered = LEVELS.filter((item) => next.includes(item));
      const fallback = def.reasoning && ordered.includes(def.reasoning.default_level) ? def.reasoning.default_level : ordered[0];
      def.reasoning = { levels: ordered, default_level: fallback, method: (def.reasoning && def.reasoning.method) || 'effort' };
    }
    redraw();
  });

  Y11.actions.register('sm.defDefault', (el) => {
    const view = defList(connOf(el.dataset.connectionId), Number(el.dataset.index));
    view.def.reasoning.default_level = el.value;
    redraw();
  });

  Y11.actions.register('sm.defMethod', (el) => {
    const view = defList(connOf(el.dataset.connectionId), Number(el.dataset.index));
    view.def.reasoning.method = el.value;
    redraw();
  });

  Y11.actions.register('sm.removeDef', (el) => {
    const view = defList(connOf(el.dataset.connectionId), Number(el.dataset.index));
    view.list.splice(Number(el.dataset.index), 1);
    redraw();
  });

  Y11.actions.register('sm.saveDefs', (el) => {
    const conn = connOf(el.dataset.connectionId);
    const result = Y11.run('catalog.connection.save', {
      connection_id: conn.id, name: conn.name, scheme: conn.scheme, protocol: conn.protocol,
      base_url: conn.base_url, credential_ref: conn.credential_ref, timeout_sec: conn.timeout_sec,
      models_url: conn.models_url || '', definitions: st.defs[conn.id].map(defPayload), base_version: cat().revision
    });
    if (!result.accepted) return;
    delete st.defs[conn.id];
    redraw();
  });

  Y11.actions.register('sm.testModel', (el) => {
    Y11.run('catalog.model.test', { definition_id: el.dataset.definitionId });
  });

  Y11.actions.register('sm.clearOverride', (el) => {
    Y11.run('credential.clear_override', { ref: el.dataset.ref, base_version: el.dataset.baseVersion });
  });

  Y11.actions.register('sm.removePersisted', (el) => {
    Y11.run('credential.remove_persisted', { ref: el.dataset.ref, base_version: el.dataset.baseVersion });
  });

  Y11.actions.register('sm.saveCred', () => {
    const ref = document.getElementById('y11-cred-ref').value.trim();
    const key = document.getElementById('y11-cred-key').value;
    const persist = document.querySelector('input[name="y11-cred-persist"]:checked').value;
    const existing = cat().credentials.find((item) => item.ref === ref);
    const params = { ref, key, persist };
    if (existing) params.base_version = existing.version;
    const result = Y11.run('credential.set', params);
    if (!result.accepted) return;
    document.getElementById('y11-cred-key').value = '';
    redraw();
  });

  Y11.actions.register('sm.jsonOpen', () => openJson());

  Y11.actions.register('sm.jsonImport', () => {
    const file = document.getElementById('y11-json-file');
    if (!file) return;
    file.click();
  });

  Y11.actions.register('sm.jsonFile', (el) => {
    const file = el.files && el.files[0];
    if (!file) return;
    file.text().then((text) => {
      st.json.text = text;
      st.json.source = file.name;
      st.json.errors = [];
      renderJsonModal();
    });
  });

  Y11.actions.register('sm.jsonFormat', () => {
    const area = document.getElementById('y11-json-text');
    let parsed;
    try {
      parsed = JSON.parse(area.value);
    } catch (error) {
      st.json.errors = [{ path: '(文档)', message: String(error.message) }];
      st.json.text = area.value;
      renderJsonModal();
      return;
    }
    st.json.text = JSON.stringify(parsed, null, 2);
    st.json.errors = [];
    renderJsonModal();
  });

  Y11.actions.register('sm.jsonReset', () => {
    const doc = Y11.api.query('catalog.document').data;
    st.json.text = JSON.stringify(doc.document, null, 2);
    st.json.source = null;
    st.json.errors = [];
    st.json.revision = doc.revision;
    renderJsonModal();
  });

  Y11.actions.register('sm.jsonCopy', () => {
    const area = document.getElementById('y11-json-text');
    area.select();
    document.execCommand('copy');
    Y11.ui.toast('已复制目录文档', 'ok');
  });

  Y11.actions.register('sm.jsonExport', () => {
    const area = document.getElementById('y11-json-text');
    const url = URL.createObjectURL(new Blob([area.value], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'catalog.json';
    link.click();
    URL.revokeObjectURL(url);
  });

  Y11.actions.register('sm.jsonSave', () => {
    const area = document.getElementById('y11-json-text');
    let parsed;
    try {
      parsed = JSON.parse(area.value);
    } catch (error) {
      st.json.errors = [{ path: '(文档)', message: String(error.message) }];
      st.json.text = area.value;
      renderJsonModal();
      return;
    }
    const result = Y11.run('catalog.document.save', { document: parsed, base_version: cat().revision });
    if (!result.accepted) {
      st.json.errors = [{ path: '(文档)', message: result.message }];
      st.json.text = area.value;
      renderJsonModal();
      return;
    }
    st.defs = {};
    st.form = null;
    Y11.ui.closeModal();
    redraw();
  });

  Y11.actions.register('sm.deptModel', (el) => {
    const dept = el.dataset.department;
    const saved = cat().department_defaults[dept];
    st.deptDraft[dept] = { definition: el.value || null, request_level: st.deptDraft[dept] ? st.deptDraft[dept].request_level : saved.request_level };
    redraw();
  });

  Y11.actions.register('sm.deptLevel', (el) => {
    const dept = el.dataset.department;
    const draft = st.deptDraft[dept] || {};
    draft.request_level = el.value || null;
    st.deptDraft[dept] = draft;
  });

  Y11.actions.register('sm.saveDept', (el) => {
    const dept = el.dataset.department;
    const draft = st.deptDraft[dept] || { definition: cat().department_defaults[dept].definition, request_level: cat().department_defaults[dept].request_level };
    const defaults = {};
    Object.keys(cat().department_defaults).forEach((key) => {
      defaults[key] = key === dept ? { definition: draft.definition, request_level: draft.request_level } : null;
    });
    const result = Y11.run('catalog.department_defaults.save', { defaults, base_version: cat().revision });
    if (!result.accepted) return;
    const warnings = result.refs && result.refs.warnings ? result.refs.warnings : [];
    warnings.forEach((warning) => Y11.ui.toast(warning.text, 'warn'));
    delete st.deptDraft[dept];
    redraw();
  });

  Y11.actions.register('sm.roleModel', (el) => {
    const roleId = el.dataset.roleId;
    const saved = cat().role_defaults[roleId];
    st.roleDraft[roleId] = { definition: el.value || null, request_level: st.roleDraft[roleId] ? st.roleDraft[roleId].request_level : saved.request_level };
    redraw();
  });

  Y11.actions.register('sm.roleLevel', (el) => {
    const roleId = el.dataset.roleId;
    const draft = st.roleDraft[roleId] || {};
    draft.request_level = el.value || null;
    st.roleDraft[roleId] = draft;
  });

  Y11.actions.register('sm.saveRole', (el) => {
    const roleId = el.dataset.roleId;
    const saved = cat().role_defaults[roleId];
    const draft = st.roleDraft[roleId] || { definition: saved.definition, request_level: saved.request_level };
    const defaults = {};
    Object.keys(cat().role_defaults).forEach((key) => {
      defaults[key] = key === roleId ? { definition: draft.definition, request_level: draft.request_level } : null;
    });
    const result = Y11.run('catalog.role_defaults.save', { defaults, base_version: cat().revision });
    if (!result.accepted) return;
    delete st.roleDraft[roleId];
    redraw();
  });
})();
