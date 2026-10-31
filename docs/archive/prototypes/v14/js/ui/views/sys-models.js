// V14 模型管理交互原型：示例状态在内存中推进，不请求服务，不写入真实目录。
(function () {
  'use strict';
  const Y = window.Y14;
  const esc = Y.esc;
  const departments = { product: '产品', engineering: '工程', quality: '质检' };
  // 数值只用于原型演示，不作为上游模型的真实能力声明。
  const examples = [
    ['deepseek-v4-flash', 'DeepSeek V4 Flash', 'DeepSeek', 256000, 32000, false, true],
    ['kimi-k2.6', 'Kimi K2.6', 'Moonshot', 262144, 32768, true, true],
    ['glm-5', 'GLM 5', 'Zhipu', 204800, 32768, false, true],
    ['qwen3.6-plus', 'Qwen 3.6 Plus', 'Qwen', 262144, 32768, true, true],
    ['mimo-v2.5', 'MiMo V2.5', 'Xiaomi', 262144, 32768, true, true],
    ['minimax-m2.7', 'MiniMax M2.7', 'MiniMax', 204800, 32768, false, true],
    ['example-code', '代码模型示例', '示例服务', 200000, 16000, false, false],
    ['example-vision', '视觉模型示例', '示例服务', 128000, 16000, true, false],
    ['example-fast', '快速模型示例', '示例服务', 128000, 8000, false, false],
    ['example-long', '长上下文模型示例', '示例服务', 1000000, 32000, true, true],
    ['example-small', '轻量模型示例', '示例服务', 64000, 8000, false, false],
    ['example-reasoning', '推理模型示例', '示例服务', 200000, 32000, false, true]
  ].map(([id, name, provider, context, output, vision, reasoning], i) => ({
    id, name, provider, context, output, vision, reasoning, type: 'chat',
    source: i % 2 ? '模型资料自动匹配' : '服务返回的模型信息', protocol: 'Chat Completions'
  }));
  const unknown = { id: 'custom-latest', name: '自定义模型', provider: '自定义服务', context: null,
    output: null, vision: false, reasoning: false, type: 'chat', source: '服务未返回容量信息', protocol: '待识别' };
  const others = Array.from({ length: 126 }, (_, i) => ({
    id: 'example-' + (i % 3 === 0 ? 'image' : i % 3 === 1 ? 'audio' : 'embedding') + '-' + String(i + 1).padStart(3, '0'),
    name: (i % 3 === 0 ? '图片生成' : i % 3 === 1 ? '语音处理' : '向量检索') + '示例 ' + (i + 1),
    provider: '示例服务', type: 'other', context: null, output: null
  }));
  const catalog = [...examples, unknown, ...others];
  const modes = {
    normal: '正常连接 · 139 个候选', auth: '获取失败 · Key 被拒绝', network: '获取失败 · 无法连接',
    empty: '获取成功 · 空列表', test: '模型验证失败', unknown: '模型容量无法识别'
  };
  let generation = 0;
  let attempt = 0;
  function initial(mode = 'normal') {
    return { mode, url: '', key: '', credentialSaved: false, editingConnection: true, showKey: false, phase: 'idle', error: '', candidates: [],
      search: '', filter: 'auto', limit: 8, selected: {}, defaults: { product: '', engineering: '', quality: '' } };
  }
  let state = initial();
  const ready = () => Object.values(state.selected).filter((row) => row.status === 'ready');
  const working = () => state.phase === 'connecting';
  const units = (value) => value === null ? '待识别' : (value / 1000).toLocaleString('en-US', { maximumFractionDigits: 1 }) + 'K';
  const wait = () => new Promise((resolve) => setTimeout(resolve, 650));
  const badge = (text, kind = '') => '<span class="tag ' + kind + '">' + esc(text) + '</span>';
  const button = (label, action, attrs = '', kind = '') => '<button type="button" class="y13-btn ' + kind + '" data-act="m14.' + action + '" ' + attrs + '>' + label + '</button>';
  function validation() {
    if (!state.url.trim()) return '填写服务 URL 和 API Key 后即可获取模型。';
    let url;
    try { url = new URL(state.url.trim()); } catch { return '请输入完整的服务 URL，例如 https://api.example.com/v1。'; }
    if (!['https:', 'http:'].includes(url.protocol)) return '服务 URL 必须使用 http 或 https。';
    if (!state.key.trim() && !state.credentialSaved) return '还需要填写 API Key。';
    return '';
  }
  function redraw() {
    if (Y.app.state.route.name !== 'sys-models') return;
    const active = document.activeElement;
    const focusId = active?.id;
    const position = active?.selectionStart;
    Y.app.renderContent(true);
    if (focusId) {
      const replacement = document.getElementById(focusId);
      if (replacement) {
        replacement.focus({ preventScroll: true });
        if (typeof position === 'number' && replacement.type !== 'url') replacement.setSelectionRange(position, position);
      }
    }
  }
  function clearModels() {
    generation += 1;
    state.phase = 'idle'; state.error = ''; state.candidates = []; state.selected = {}; state.credentialSaved = false;
    state.defaults = { product: '', engineering: '', quality: '' };
  }
  function statusLabel(row) {
    return ({ metadata: '正在补全参数…', testing: '正在验证调用…', ready: '已启用', failed: '验证失败', unknown: '无法识别容量' })[row.status];
  }
  function connection() {
    const connected = state.phase === 'connected';
    const issue = validation();
    if (connected && !state.editingConnection) {
      return '<section class="panel panel-body"><div class="panel-head"><div class="panel-title"><span class="number">01</span><h2>模型服务已连接</h2></div>' + badge('已连接', 'ok') + '</div>' +
        '<p class="small" style="overflow-wrap:anywhere">' + esc(state.url) + '</p><p class="small muted" style="margin-top:7px">API Key 已保存 · 已获取 ' + state.candidates.length + ' 个模型</p>' +
        '<div class="hint ok" style="margin-top:18px" role="status">连接信息已保存 · 已获取 ' + state.candidates.length + ' 个模型，接下来只需勾选。</div>' +
        '<div class="connect-foot" style="margin-top:16px">' + button('修改 URL 或 Key', 'editConnection') + button('刷新模型列表', 'connect', '', 'small') + '</div></section>';
    }
    let message = '';
    if (state.error) message = '<div class="hint error" role="alert"><strong>' + esc(state.error) + '</strong>' +
      (state.mode === 'auth' ? '请修改上方 API Key，再次获取模型。' : '请检查 URL、网络和服务状态，再次获取模型。') + '</div>';
    if (connected) message = '<div class="hint ok" role="status">' + Y.ui.icon('succeeded') +
      ' 连接信息已保存 · 已获取 ' + state.candidates.length + ' 个模型，接下来只需勾选。</div>';
    if (working()) message = '<div class="hint" role="status">正在保存连接信息并获取模型列表…</div>';
    return '<section class="panel panel-body"><div class="panel-head"><div class="panel-title"><span class="number">01</span><h2>连接模型服务</h2></div>' +
      badge(connected ? '已连接' : working() ? '连接中' : '填写两项即可', connected ? 'ok' : '') + '</div>' +
      '<form id="m14-connect-form"><label class="field" for="m14-url">服务 URL<input id="m14-url" type="url" required autocomplete="off" spellcheck="false" placeholder="https://api.example.com/v1" value="' + esc(state.url) + '" data-act="m14.url">' +
      '<span class="field-note">填写服务提供的 API 地址。</span></label>' +
      '<label class="field" for="m14-key">API Key<span class="key-wrap"><input id="m14-key" type="' + (state.showKey ? 'text' : 'password') + '" ' + (state.credentialSaved ? '' : 'required') + ' autocomplete="off" spellcheck="false" placeholder="' + (state.credentialSaved ? '已保存 · 输入以更换 Key' : '输入 API Key') + '" value="' + esc(state.key) + '" data-act="m14.key">' +
      button(state.showKey ? '隐藏' : '显示', 'showKey', 'aria-label="' + (state.showKey ? '隐藏' : '显示') + ' API Key"') + '</span>' +
      '<span class="field-note">连接、凭据和模型配置随操作自动保存。</span></label>' +
      '<div class="connect-foot"><button id="m14-connect" type="submit" class="y13-btn primary" ' + (working() ? 'disabled' : '') + '>' +
      (working() ? '正在获取…' : connected ? '刷新模型列表' : '获取模型，开始选择') + '</button>' +
      '<span class="small muted" id="m14-input-hint">' + esc(working() ? '正在处理，请稍候。' : connected ? '修改 URL 或 Key 后会重新验证。' : issue || '已填写完整，可以获取模型。') + '</span></div></form>' +
      (message ? '<div style="margin-top:16px">' + message + '</div>' : '') + '</section>';
  }
  function usage() {
    const available = ready();
    return '<section class="panel panel-body"><div class="panel-head"><div class="panel-title"><span class="number">' + Y.ui.icon('models') + '</span><h2>部门使用</h2></div>' +
      badge(available.length ? '已自动保存' : '自动配置', available.length ? 'ok' : '') + '</div>' +
      (available.length ? Object.entries(departments).map(([id, label]) => '<div class="usage-row"><label for="m14-dept-' + id + '">' + label + '</label>' +
        '<select id="m14-dept-' + id + '" data-act="m14.department" data-department="' + id + '">' + available.map((row) =>
          '<option value="' + esc(row.id) + '" ' + (state.defaults[id] === row.id ? 'selected' : '') + '>' + esc(row.name) + '</option>').join('') + '</select></div>').join('') +
        '<p class="usage-note">首个启用的模型自动供三个部门使用。需要分别选择时，在这里切换即生效。</p>' :
        '<div class="usage-empty"><div class="symbol">' + Y.ui.icon('models') + '</div><p>选好模型，部门就能开始工作</p><p class="small" style="margin-top:6px">首个通过验证的模型会自动供三个部门使用。</p></div>') + '</section>';
  }
  function filtered() {
    const search = state.search.trim().toLowerCase();
    return state.candidates.filter((row) => {
      const matches = !search || (row.id + ' ' + row.name + ' ' + row.provider).toLowerCase().includes(search);
      const filter = state.filter === 'all' || (state.filter === 'auto' && row.type === 'chat' && row.context !== null) ||
        (state.filter === 'vision' && row.vision) || (state.filter === 'reasoning' && row.reasoning) ||
        (state.filter === 'selected' && state.selected[row.id]);
      return matches && filter;
    });
  }
  function modelCard(row) {
    const selected = state.selected[row.id];
    const label = selected ? statusLabel(selected) : row.type === 'other' ? '不适用于部门' : '选择即配置';
    const statusKind = selected?.status === 'failed' ? 'error' : selected?.status === 'unknown' ? 'warn' : '';
    return '<article class="model-card ' + (selected ? 'selected' : '') + '" data-model="' + esc(row.id) + '">' +
      '<button type="button" class="model-pick" role="checkbox" aria-checked="' + Boolean(selected) + '" aria-label="选择 ' + esc(row.name) + '" data-act="m14.pick" data-id="' + esc(row.id) + '" ' + (row.type === 'other' ? 'disabled' : '') + '>' +
      '<span class="check" aria-hidden="true">✓</span><span class="model-info"><span class="model-name">' + esc(row.name) +
      (row.vision ? badge('图像输入') : '') + (row.reasoning ? badge('推理') : '') + '</span><span class="model-id">' + esc(row.provider) + ' · ' + esc(row.id) + '</span>' +
      '<span class="specs">' + (row.type === 'other' ? '图片、语音或向量服务，无法执行部门任务。' :
        '上下文 ' + units(row.context) + '<span class="separator">/</span>最大输出 ' + units(row.output)) + '</span></span>' +
      '<span class="model-status ' + statusKind + '">' + label + '</span></button>' +
      (selected?.error ? '<div class="model-error" role="alert">' + esc(selected.error) + '<br>' +
        button(selected.status === 'unknown' ? '重新识别' : '重新验证', 'retry', 'data-id="' + esc(row.id) + '"', 'small') + '</div>' : '') +
      (selected?.status === 'ready' ? '<details class="model-detail"><summary>已自动配置 · 查看参数与验证结果</summary><p>上下文窗口：' + row.context.toLocaleString() +
        ' tokens；最大输出：' + row.output.toLocaleString() + ' tokens。<br>协议：' + row.protocol + '；工具调用：验证通过；图像输入：' +
        (row.vision ? '支持' : '不支持') + '。<br>参数来源：' + esc(row.source) + '。本页全部为演示读数。</p></details>' : '') + '</article>';
  }
  function selectedPanel() {
    const entries = Object.values(state.selected);
    const available = ready().length;
    return '<aside class="selection" aria-label="已选模型"><h3>已选模型 <span class="tag">' + entries.length + '</span></h3><p class="small muted">勾选后自动补全参数并验证</p>' +
      (entries.length ? entries.map((row) => '<div class="selection-item"><div class="row"><strong>' + esc(row.name) + '</strong><button class="remove" data-act="m14.remove" data-id="' + esc(row.id) + '" aria-label="移除 ' + esc(row.name) + '">×</button></div>' +
        '<p class="small ' + (row.status === 'ready' ? '' : 'muted') + '">' + statusLabel(row) + '</p></div>').join('') :
        '<p class="small muted" style="padding:26px 0">在左侧选择你想使用的模型。<br>容量和协议由系统处理。</p>') +
      (available ? '<div class="hint ok" role="status"><strong>' + available + ' 个模型已启用</strong>配置已生效，可以直接开始工作。</div>' +
        '<div style="margin-top:14px">' + button('返回项目开始工作', 'home', '', 'primary') + '</div>' :
        entries.length ? '<div class="hint">' + (entries.some((row) => ['metadata', 'testing'].includes(row.status)) ? '配置和验证正在进行，结果会自动出现在这里。' : '当前没有可用模型。请按模型旁的提示处理，或选择其他模型。') + '</div>' : '') + '</aside>';
  }
  function results() {
    if (state.phase !== 'connected') return '<div class="zero"><strong>' + (working() ? '正在获取模型…' : '连接服务后，在这里选择模型') +
      '</strong><p>' + (working() ? '获取完成后会自动整理候选。' : '只需填写上方的 URL 和 Key，系统会整理可使用的模型。') +
      '</p><div class="placeholder-lines" aria-hidden="true"><span></span><span></span><span></span></div></div>';
    if (!state.candidates.length) return '<div class="zero"><strong>服务没有返回任何模型</strong><p>连接已成功，请检查这个 Key 的模型权限，或刷新列表。</p>' + button('刷新模型列表', 'connect') + '</div>';
    const rows = filtered();
    return '<div class="model-layout"><div class="model-results"><div class="results-meta" role="status">' +
      (state.filter === 'auto' ? rows.length + ' 个模型可自动配置 · 其他候选可在「全部模型」中查看' : '找到 ' + rows.length + ' 个模型') + '</div>' +
      (rows.length ? rows.slice(0, state.limit).map(modelCard).join('') : '<div class="zero"><strong>没有符合条件的模型</strong><p>试试模型名称、提供方或上游模型 ID。</p>' + button('清除搜索和筛选', 'clearSearch') + '</div>') +
      (rows.length > state.limit ? button('继续显示 ' + Math.min(12, rows.length - state.limit) + ' 个模型', 'more', '', 'small page-button') : '') +
      '</div>' + selectedPanel() + '</div>';
  }
  function models() {
    return '<section class="panel"><div class="models-head"><div class="panel-head"><div class="panel-title"><span class="number">02</span><h2>选择要使用的模型</h2></div>' +
      '<span class="small muted">选中后自动配置，无须单独保存或测试</span></div>' +
      '<div class="search-line"><label class="search">' + Y.ui.icon('search') + '<input id="m14-search" type="search" aria-label="搜索模型" placeholder="搜索模型名称、提供方或模型 ID…" value="' + esc(state.search) + '" data-act="m14.search" ' + (state.phase !== 'connected' ? 'disabled' : '') + '></label></div>' +
      '<div class="filters" role="group" aria-label="筛选模型">' + [['auto', '可自动配置'], ['vision', '支持图像'], ['reasoning', '支持推理'], ['all', '全部模型'], ['selected', '已选择']].map(([id, label]) =>
        '<button class="filter" data-act="m14.filter" data-filter="' + id + '" aria-pressed="' + (state.filter === id) + '" ' + (state.phase !== 'connected' ? 'disabled' : '') + '>' + label + '</button>').join('') + '</div></div>' +
      results() + '<div class="models-footer"><span>' + (state.phase === 'connected' ? '来源：' + esc(state.url.replace(/\/$/, '')) + '/models · 本次会话的示例列表' : '获取完成后按模型用途整理候选') +
      '</span><span>上下文、最大输出、协议自动填写</span></div></section>';
  }
  function demo() {
    return '<details class="demo" id="m14-demo"><summary>原型演示 · 切换异常场景 / 一键填入示例</summary><p class="small" style="margin-top:10px">这里控制演示条件，不连接真实模型服务。所有容量、延迟和验证结果均为示例；请使用示例 Key。</p>' +
      '<div class="demo-controls"><label for="m14-mode">演示场景</label><select id="m14-mode" data-act="m14.mode">' + Object.entries(modes).map(([id, name]) => '<option value="' + id + '" ' + (state.mode === id ? 'selected' : '') + '>' + name + '</option>').join('') +
      '</select>' + button('填入示例 URL 和 Key', 'example') + button('重新开始', 'reset') + '</div><div class="demo-state" aria-live="polite"><span>连接：' +
      ({ idle: '待连接', connecting: '获取中', connected: '已连接', failed: '失败' })[state.phase] + '</span><span>已选：' + Object.keys(state.selected).length + '</span><span>可用：' + ready().length +
      '</span><span>部门配置：' + Object.values(state.defaults).filter(Boolean).length + '/3</span></div></details>';
  }
  function render() {
    const connected = state.phase === 'connected';
    return '<div class="m14"><div class="intro"><div><p class="eyebrow">MODEL CONNECTION</p><h1>选好模型，就可以开始。</h1><p class="lead">填写服务地址和 Key，剩下交给系统。参数自动补全，选择后即可使用。</p></div>' +
      '<div class="flow" aria-label="配置进度"><span class="' + (connected ? 'done' : '') + '"><b>' + (connected ? '✓' : '1') + '</b>连接服务</span><span>→</span><span class="' + (ready().length ? 'done' : '') + '"><b>' +
      (ready().length ? '✓' : '2') + '</b>选择模型</span><span>→</span><span class="' + (ready().length ? 'done' : '') + '"><b>' + (ready().length ? '✓' : '3') + '</b>直接使用</span></div></div>' +
      '<div class="top-grid">' + connection() + usage() + '</div>' + models() + demo() + '</div>';
  }
  async function connect() {
    if (working()) return;
    const issue = validation();
    if (issue) { document.getElementById('m14-connect-form').reportValidity(); return; }
    const existing = state.phase === 'connected';
    const run = ++generation;
    state.phase = 'connecting'; state.error = ''; redraw();
    await wait();
    if (run !== generation) return;
    if ((state.mode === 'auth' && state.key.includes('invalid')) || (state.mode === 'network' && state.url.includes('.invalid'))) {
      state.phase = 'failed';
      state.error = state.mode === 'auth' ? 'HTTP 401 · 服务拒绝了这个 API Key' : '连接失败 · 无法到达模型服务';
    } else {
      state.phase = 'connected';
      state.url = state.url.trim().replace(/\/$/, '');
      state.candidates = state.mode === 'empty' ? [] : state.mode === 'unknown' ? [unknown, ...examples] : catalog;
      if (!existing) { state.filter = state.mode === 'unknown' ? 'all' : 'auto'; state.limit = 8; }
      state.key = ''; state.credentialSaved = true; state.showKey = false; state.editingConnection = false;
    }
    redraw();
  }
  async function configure(id) {
    const model = state.candidates.find((row) => row.id === id);
    const ticket = ++attempt;
    const run = generation;
    state.selected[id] = { ...model, status: 'metadata', ticket };
    redraw();
    const current = () => run === generation && state.selected[id]?.ticket === ticket;
    await wait();
    if (!current()) return;
    if (model.context === null || model.output === null) {
      Object.assign(state.selected[id], { status: 'unknown', error: '服务没有返回上下文窗口和最大输出，也未找到可信的模型资料。暂不能启用；可以重新识别，或选择已识别的模型。' });
      redraw(); return;
    }
    state.selected[id].status = 'testing'; redraw();
    await wait();
    if (!current()) return;
    if (state.mode === 'test' && id === examples[0].id) {
      Object.assign(state.selected[id], { status: 'failed', error: 'HTTP 403 · 当前 Key 没有调用这个模型的权限。请选择其他模型，或修改 Key 后重新连接。' });
    } else {
      state.selected[id].status = 'ready';
      Object.keys(state.defaults).forEach((dept) => { if (!state.defaults[dept]) state.defaults[dept] = id; });
    }
    redraw();
  }
  function remove(id) {
    delete state.selected[id];
    const next = ready()[0]?.id || '';
    Object.keys(state.defaults).forEach((dept) => { if (state.defaults[dept] === id) state.defaults[dept] = next; });
    redraw();
  }
  function input(field, value) {
    if (state[field] === value) return;
    if (state.phase !== 'idle') clearModels();
    state[field] = value;
    redraw();
  }
  Y.views.register('sys-models', {
    title: () => '模型管理', render,
    mount(ctx, root) {
      root.querySelector('#m14-connect-form')?.addEventListener('submit', (event) => { event.preventDefault(); connect(); });
    }
  });
  Y.actions.register('m14.url', (el) => input('url', el.value));
  Y.actions.register('m14.key', (el) => input('key', el.value));
  Y.actions.register('m14.showKey', () => { state.showKey = !state.showKey; redraw(); });
  Y.actions.register('m14.connect', connect);
  Y.actions.register('m14.editConnection', () => { state.editingConnection = true; redraw(); document.getElementById('m14-url').focus(); });
  Y.actions.register('m14.example', () => {
    clearModels(); state.editingConnection = true;
    state.url = state.mode === 'network' ? 'https://unreachable.invalid/v1' : 'https://api.example.com/v1';
    state.key = state.mode === 'auth' ? 'example-key-invalid' : 'example-key-for-prototype'; redraw();
  });
  Y.actions.register('m14.search', (el) => { state.search = el.value; state.limit = 8; redraw(); });
  Y.actions.register('m14.filter', (el) => { state.filter = el.dataset.filter; state.limit = 8; redraw(); });
  Y.actions.register('m14.clearSearch', () => { state.search = ''; state.filter = 'all'; state.limit = 8; redraw(); });
  Y.actions.register('m14.more', () => { state.limit += 12; redraw(); });
  Y.actions.register('m14.pick', (el) => { const id = el.dataset.id; if (state.selected[id]) remove(id); else configure(id); });
  Y.actions.register('m14.remove', (el) => remove(el.dataset.id));
  Y.actions.register('m14.retry', (el) => configure(el.dataset.id));
  Y.actions.register('m14.department', (el) => { state.defaults[el.dataset.department] = el.value; redraw(); });
  Y.actions.register('m14.mode', (el) => { generation += 1; state = initial(el.value); redraw(); document.getElementById('m14-demo').open = true; });
  Y.actions.register('m14.reset', () => { generation += 1; state = initial(state.mode); redraw(); });
  Y.actions.register('m14.home', () => Y.go('#/home'));
})();
