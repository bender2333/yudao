// 模型管理页：连接服务 → 获取候选 → 勾选后自动补全参数并验证 → 首个可用的模型自动成为三个部门的默认 → 部门使用。
// 主流程和失败情形取自 v14，其余按模型管理设计说明第 9 节补；状态只在内存里，刷新页面回到起点，不发任何请求。
(function () {
  'use strict';
  const Y15 = window.Y15;
  const esc = Y15.esc;
  const ui = Y15.ui;

  const DEPTS = { product: '产品', engineering: '工程', quality: '质检' };
  const LEVELS = { minimal: '极低', low: '低', medium: '中', high: '高', xhigh: '很高', max: '最高' };
  const MAX_TEST = 3;
  const STEP_MS = 650;

  // 数值只用于演示，不代表上游模型的真实能力
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
    id, name, provider, context, output, vision, reasoning, type: 'chat', protocol: 'Chat Completions',
    levels: reasoning ? ['low', 'medium', 'high'] : [], source: i % 2 ? '模型能力表（服务商 DeepSeek 等，第 41 版，快照 2026-10-30）' : '上游模型列表'
  }));
  const unknown = { id: 'custom-latest', name: '自定义模型', provider: '自定义服务', context: null, output: null, vision: false, reasoning: false, type: 'chat', protocol: 'Chat Completions', levels: [], source: '上游模型列表没有给出容量' };
  const others = Array.from({ length: 126 }, (_, i) => ({
    id: 'example-' + (i % 3 === 0 ? 'image' : i % 3 === 1 ? 'audio' : 'embedding') + '-' + String(i + 1).padStart(3, '0'),
    name: (i % 3 === 0 ? '图片生成' : i % 3 === 1 ? '语音处理' : '向量检索') + '示例 ' + (i + 1), provider: '示例服务', type: 'other', context: null, output: null, levels: []
  }));
  const catalog = [...examples, unknown, ...others];

  const MODES = {
    normal: '正常连接 · 139 个候选', auth: '获取失败 · Key 被拒绝', network: '获取失败 · 无法连接', notlist: '获取失败 · 返回的不是模型列表',
    path: '获取失败 · 地址多写了请求路径', empty: '获取成功 · 空列表', test: '验证失败', unknown: '容量无法识别'
  };

  let generation = 0;
  let attempt = 0;
  let state = initial('normal');
  let demoOpen = false;

  function initial(mode) {
    return { mode, url: '', key: '', savedUrl: '', saved: false, editing: true, showKey: false, phase: 'idle', error: null, fetchedAt: null, candidates: [],
      search: '', filter: 'auto', limit: 8, selected: {}, defaults: { product: '', engineering: '', quality: '' }, levels: { product: '', engineering: '', quality: '' },
      roles: {}, notice: '', manualOpen: false };
  }

  const rows = () => Object.values(state.selected);
  const ready = () => rows().filter((r) => r.status === 'ready');
  const busy = () => state.phase === 'connecting';
  const units = (v) => (v === null ? '待识别' : (v / 1000).toLocaleString('en-US', { maximumFractionDigits: 1 }) + 'K');
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms || STEP_MS));
  const tag = (text, kind) => '<span class="m15-tag' + (kind ? ' is-' + kind : '') + '">' + esc(text) + '</span>';
  const btn = (label, act, attrs, kind) => '<button type="button" class="y15-btn' + (kind ? ' ' + kind : '') + '" data-act="m15.' + act + '"' + (attrs ? ' ' + attrs : '') + '>' + esc(label) + '</button>';
  const hostOf = (url) => { try { return new URL(url).host; } catch (e) { return url; } };

  // 地址的规范形式：缺协议头补 https://，主机名小写，去掉末尾的 /
  function normalize(text) {
    let t = text.trim();
    if (!t) return '';
    if (!/^https?:\/\//i.test(t)) t = 'https://' + t;
    try { const u = new URL(t); return (u.origin + u.pathname).replace(/\/+$/, ''); } catch (e) { return ''; }
  }
  function issue() {
    if (!state.url.trim()) return '还缺服务地址。';
    if (!normalize(state.url)) return '服务地址写得不完整，例如 https://api.example.com/v1。';
    if (!state.key.trim() && !state.saved) return '还缺 API Key。';
    return '';
  }

  function redraw() {
    if (!Y15.state.route || Y15.state.route.name !== 'sys-models') return;
    const a = document.activeElement;
    const id = a && a.id;
    const pos = a && a.selectionStart;
    Y15.rerender();
    if (id) {
      const n = document.getElementById(id);
      if (n) { n.focus({ preventScroll: true }); if (typeof pos === 'number' && n.type !== 'url') { try { n.setSelectionRange(pos, pos); } catch (e) { /* 不支持选区的输入框 */ } } }
    }
  }

  // 谁在引用这个模型
  function refsOf(id) {
    const out = [];
    Object.keys(DEPTS).forEach((d) => {
      if (state.defaults[d] === id) out.push(DEPTS[d] + '的部门使用');
      Object.keys(state.roles).forEach((k) => { if (k.indexOf(d + '|') === 0 && state.roles[k] === id) out.push(DEPTS[d] + '的「' + k.split('|')[1] + '」角色'); });
    });
    return out;
  }

  const STATUS = { metadata: '补全参数', waiting: '等待验证', testing: '验证调用', ready: '已启用', failed: '验证失败', unknown: '容量未知', stale: '准入已作废' };

  // ---------------------------------------------------------------- 区域一：连接服务

  function connectionBlock() {
    const connected = state.phase === 'connected';
    const problem = issue();
    const showForm = !connected || state.editing;
    let card = '';
    if (connected) {
      card = '<div class="m15-conn-card"><div class="m15-conn-head"><strong class="m15-wrap">' + esc(state.savedUrl) + '</strong>' + tag('已连接', 'ok') + '</div>' +
        ui.kv([['API Key', '已保存 · 来源：数据目录里的凭据文件'], ['最近一次获取', '成功，' + state.candidates.length + ' 个候选 · ' + esc(ui.time(Y15.app.now())) + ' · 来源 ' + esc(state.savedUrl) + '/models']], 'is-rows') +
        '<div class="y15-row">' + btn('修改地址或 Key', 'edit', '', 'small') + btn('刷新模型列表', 'connect', '', 'small') + btn('删除', 'delete', '', 'small danger') + '</div></div>';
    }
    let msg = '';
    if (busy()) msg = '<div class="m15-hint" role="status">正在保存连接并获取模型列表……</div>';
    else if (state.error) {
      const e = state.error;
      msg = '<div class="m15-hint is-error" role="alert"><strong>' + esc(e.title) + '</strong>请求的地址：' + esc(e.url) + '<br>' + esc(e.detail) + '<br>' + esc(e.hint) + '</div>';
    } else if (state.phase === 'connected' && !state.candidates.length) msg = '<div class="m15-hint is-warn" role="status"><strong>已连接，但服务没有返回任何模型</strong>请检查这个 Key 的模型权限后刷新列表，或在下面用「手动添加」。</div>';
    else if (state.phase === 'connected') msg = '<div class="m15-hint is-ok" role="status">连接和 Key 已保存，获取到 ' + state.candidates.length + ' 个候选，接下来只需勾选。</div>';
    const form = showForm
      ? '<form id="m15-form" class="y15-form"><label class="y15-field" for="m15-url"><span>服务地址</span><input class="y15-input" id="m15-url" type="text" autocomplete="off" spellcheck="false" placeholder="https://api.example.com/v1" value="' + esc(state.url) + '">' +
        '<small class="y15-muted">没写 http:// 或 https:// 时按 https:// 处理。同一个地址只有一份连接，再次提交会更新它的 Key 并重新获取。</small></label>' +
        '<label class="y15-field" for="m15-key"><span>API Key</span><span class="m15-keywrap"><input class="y15-input" id="m15-key" type="' + (state.showKey ? 'text' : 'password') + '" autocomplete="off" spellcheck="false" placeholder="' + (state.saved ? '已保存 · 输入新的 Key 才会更换' : '输入 API Key') + '" value="' + esc(state.key) + '">' +
        btn(state.showKey ? '隐藏' : '显示', 'showKey', 'aria-label="' + (state.showKey ? '隐藏' : '显示') + ' API Key"', 'small') + '</span>' +
        '<small class="y15-muted">Key 随连接保存在数据目录里，输入框始终为空，不会回填。</small></label>' +
        '<div class="y15-row"><button id="m15-connect" type="submit" class="y15-btn primary"' + (problem || busy() ? ' disabled' : '') + '>' + (busy() ? '正在获取……' : '获取模型') + '</button>' +
        '<span class="y15-small y15-muted" id="m15-hint">' + esc(busy() ? '请稍候。' : problem || '填好了，可以获取模型。') + '</span></div></form>'
      : '';
    return '<section class="m15-panel" id="m15-conn"><div class="m15-panel-head"><div class="m15-title"><span class="m15-num">1</span><h2>连接服务</h2></div>' +
      tag(state.phase === 'connected' ? '已连接' : busy() ? '连接中' : state.phase === 'failed' ? '获取失败' : '填写两项即可', state.phase === 'connected' ? 'ok' : state.phase === 'failed' ? 'error' : '') + '</div>' +
      card + form + (msg ? '<div class="m15-gap">' + msg + '</div>' : '') + '</section>';
  }

  // ---------------------------------------------------------------- 区域二：部门使用

  function deptRow(d) {
    const avail = ready();
    const cur = state.defaults[d];
    const curRow = cur && state.selected[cur];
    const stale = cur && (!curRow || curRow.status !== 'ready');
    const opts = '<option value="">未设置</option>' + (stale ? '<option value="' + esc(cur) + '" selected disabled>' + esc(curRow ? curRow.name : cur) + '（无法使用：准入已作废）</option>' : '') +
      '<optgroup label="' + esc(hostOf(state.savedUrl) || '连接') + '">' + avail.map((r) => '<option value="' + esc(r.id) + '"' + (cur === r.id ? ' selected' : '') + '>' + esc(r.name) + '</option>').join('') + '</optgroup>';
    const model = curRow && curRow.status === 'ready' ? curRow : null;
    const remind = d === 'quality' && model && !model.vision
      ? '<div class="m15-remind">提醒：质检最好用能看图像的模型。「' + esc(model.name) + '」不能看图像，质检不会得到截图和桌面操作，依赖外观或桌面程序的验收条件无法核验。仍然可以使用。</div>' : '';
    const lvOpts = model && model.levels.length
      ? '<option value="">跟随模型默认</option>' + model.levels.map((l) => '<option value="' + l + '"' + (state.levels[d] === l ? ' selected' : '') + '>' + LEVELS[l] + '</option>').join('')
      : '<option value="">跟随模型默认</option>';
    const roles = (Y15.EXTRA.deptRoles[d] || []).map((r) => {
      const key = d + '|' + r;
      const rm = state.roles[key] && state.selected[state.roles[key]];
      const ro = '<option value="">跟随部门使用</option>' + avail.map((a) => '<option value="' + esc(a.id) + '"' + (state.roles[key] === a.id ? ' selected' : '') + '>' + esc(a.name) + '</option>').join('');
      return '<label class="m15-role"><span>' + esc(r) + '</span><select class="y15-select" data-act="m15.role" data-key="' + esc(key) + '">' + ro + '</select></label>' +
        (d === 'quality' && rm && !rm.vision ? '<div class="m15-remind">提醒：「' + esc(rm.name) + '」不能看图像，影响同上。</div>' : '');
    }).join('');
    return '<div class="m15-use"><div class="m15-use-main"><label for="m15-dept-' + d + '">' + DEPTS[d] + '</label><select class="y15-select" id="m15-dept-' + d + '" data-act="m15.department" data-department="' + d + '">' + opts + '</select></div>' + remind +
      '<details class="m15-more"><summary>更多</summary><label class="m15-role"><span>请求档位</span><select class="y15-select" data-act="m15.level" data-department="' + d + '"' + (model && model.levels.length ? '' : ' disabled') + '>' + lvOpts + '</select></label>' +
      (model && !model.levels.length ? '<p class="y15-small y15-muted">该模型未声明推理档位，请求不带推理参数。</p>' : '') +
      (model ? '' : '<p class="y15-small y15-muted">先选定部门使用的模型，才能设请求档位。</p>') +
      '<h4 class="m15-sub">本部门各角色的模型</h4>' + (avail.length ? roles : '<p class="y15-small y15-muted">还没有已启用的模型。</p>') + '</details></div>';
  }

  function usageBlock() {
    const avail = ready();
    return '<section class="m15-panel" id="m15-usage"><div class="m15-panel-head"><div class="m15-title"><span class="m15-num">' + ui.icon('models') + '</span><h2>部门使用</h2></div>' +
      tag(avail.length ? '选中即保存' : '自动配置', avail.length ? 'ok' : '') + '</div>' +
      (avail.length || Object.values(state.defaults).some(Boolean)
        ? Object.keys(DEPTS).map(deptRow).join('') + '<p class="m15-note">从各部门下一次模型请求起生效；没有另选模型的项目同样生效，包括进行中的事项。首个启用的模型会自动成为还没有设置的部门的使用模型。</p>'
        : '<div class="m15-empty"><div class="m15-symbol">' + ui.icon('models') + '</div><p>选好模型，部门就能开始工作</p><p class="y15-small">首个通过验证的模型会自动供产品、工程、质检三个部门使用。</p></div>') + '</section>';
  }

  // ---------------------------------------------------------------- 区域三：选择模型

  function filtered() {
    const s = state.search.trim().toLowerCase();
    return state.candidates.filter((r) => {
      const hit = !s || (r.id + ' ' + r.name + ' ' + r.provider).toLowerCase().includes(s);
      const f = state.filter === 'all' || (state.filter === 'auto' && r.type === 'chat' && r.context !== null) || (state.filter === 'vision' && r.vision) ||
        (state.filter === 'reasoning' && r.reasoning) || (state.filter === 'selected' && state.selected[r.id]);
      return hit && f;
    });
  }

  function card(r) {
    const sel = state.selected[r.id];
    const label = sel ? STATUS[sel.status] : r.type === 'other' ? '不适用于部门任务' : r.context === null ? '容量未知' : '勾选即配置';
    const kind = sel && sel.status === 'failed' ? 'error' : sel && (sel.status === 'unknown' || sel.status === 'stale') ? 'warn' : '';
    return '<article class="m15-card' + (sel ? ' is-selected' : '') + '"><button type="button" class="m15-pick" role="checkbox" aria-checked="' + Boolean(sel) + '" aria-label="选用 ' + esc(r.name) + '" data-act="m15.pick" data-id="' + esc(r.id) + '"' + (r.type === 'other' ? ' disabled' : '') + '>' +
      '<span class="m15-check" aria-hidden="true">✓</span><span class="m15-info"><span class="m15-name">' + esc(r.name) + (r.vision ? tag('图像输入') : '') + (r.reasoning ? tag('推理') : '') + '</span>' +
      '<span class="m15-mid">' + esc(r.provider) + ' · ' + esc(r.id) + '</span><span class="m15-specs">' +
      (r.type === 'other' ? '图片、语音或向量服务，无法执行部门任务。' : '上下文 ' + units(r.context) + ' / 最大输出 ' + units(r.output) + (r.context === null ? '' : ' · ' + (r.source.indexOf('能力表') >= 0 ? '来自模型能力表' : '来自上游模型列表'))) + '</span></span>' +
      '<span class="m15-state ' + kind + '">' + label + '</span></button></article>';
  }

  function selectionRow(r) {
    let body = '<p class="y15-small' + (r.status === 'ready' ? '' : ' y15-muted') + '">' + STATUS[r.status] + (r.status === 'waiting' ? '（同时验证最多 ' + MAX_TEST + ' 个）' : '') + '</p>';
    if (r.error) body += '<p class="m15-err">' + esc(r.error) + '</p>';
    if (r.status === 'failed' || r.status === 'stale') body += '<div class="y15-row">' + btn('重新验证', 'retry', 'data-id="' + esc(r.id) + '"', 'small') + '</div>';
    if (r.status === 'unknown') {
      body += '<div class="m15-fill"><label>上下文窗口（K）<input class="y15-input" id="m15-win-' + esc(r.id) + '" type="number" min="1" placeholder="例如 128"></label>' +
        '<label>最大输出（K）<input class="y15-input" id="m15-out-' + esc(r.id) + '" type="number" min="1" placeholder="例如 16"></label>' +
        btn('填好了，继续验证', 'fill', 'data-id="' + esc(r.id) + '"', 'small primary') + '</div>';
    }
    if (r.status === 'ready') {
      body += '<details class="m15-detail"><summary>已自动配置 · 查看参数与验证结果</summary><p>上下文窗口 ' + r.context.toLocaleString() + '，最大输出 ' + r.output.toLocaleString() + '（来源：' + esc(r.source) + '）。<br>' +
        '协议：' + esc(r.protocol) + '；图像输入：' + (r.vision ? '支持' : '不支持') + '；要求调用工具：接受。<br>验证：最小问答与工具往返都通过，用时 ' + r.took + ' 秒，实际返回的模型 ' + esc(r.id) + '。<br>全部是演示读数。</p></details>';
    }
    const refs = refsOf(r.id);
    return '<div class="m15-sel"><div class="m15-sel-top"><strong>' + esc(r.name) + '</strong><button type="button" class="m15-x" data-act="m15.remove" data-id="' + esc(r.id) + '" aria-label="取消选用 ' + esc(r.name) + '" title="' + (refs.length ? '被' + esc(refs.join('、')) + '引用，不能取消' : '取消选用') + '">×</button></div>' + body + '</div>';
  }

  function selectionPanel() {
    const list = rows();
    const n = ready().length;
    const working = list.some((r) => ['metadata', 'waiting', 'testing'].includes(r.status));
    return '<aside class="m15-selection" aria-label="已选模型"><h3>已选模型 ' + tag(String(list.length)) + '</h3><p class="y15-small y15-muted">勾选后自动补全参数并验证</p>' +
      (state.notice ? '<div class="m15-hint is-warn" role="alert">' + esc(state.notice) + '</div>' : '') +
      (list.length ? list.map(selectionRow).join('') : '<p class="y15-small y15-muted m15-pad">在左边勾选想用的模型。<br>容量和协议由系统补全。</p>') +
      (n ? '<div class="m15-hint is-ok" role="status"><strong>' + n + ' 个模型已启用</strong>已在部门使用里生效。</div><div class="m15-gap">' + btn('返回原界面', 'back', '', 'primary') + '</div>'
        : list.length ? '<div class="m15-hint">' + (working ? '正在补全参数和验证，结果会出现在这里。' : '现在没有可用的模型，按每一行的提示处理，或选择别的模型。') + '</div>' : '') + '</aside>';
  }

  function results() {
    if (state.phase !== 'connected') {
      return '<div class="m15-zero"><strong>' + (busy() ? '正在获取模型……' : '连接服务后，在这里选择模型') + '</strong><p>' + (busy() ? '获取完成后会自动整理候选。' : '只需要填上面的服务地址和 Key。') + '</p></div>';
    }
    if (!state.candidates.length) return '<div class="m15-zero"><strong>服务没有返回任何模型</strong><p>连接成功，请检查这个 Key 的模型权限，刷新列表，或用下面的「手动添加」。</p>' + btn('刷新模型列表', 'connect', '', 'small') + '</div>';
    const list = filtered();
    return '<div class="m15-layout"><div class="m15-results"><div class="m15-meta" role="status">' +
      (state.filter === 'auto' ? list.length + ' 个模型可以自动配置 · 其他候选在「全部模型」里' : '找到 ' + list.length + ' 个模型') + '</div>' +
      (list.length ? list.slice(0, state.limit).map(card).join('') : '<div class="m15-zero"><strong>没有符合条件的模型</strong><p>试试模型名称、提供方或上游模型 ID。</p>' + btn('清除搜索和筛选', 'clear', '', 'small') + '</div>') +
      (list.length > state.limit ? btn('继续显示 ' + Math.min(12, list.length - state.limit) + ' 个', 'more', '', 'small m15-morebtn') : '') + '</div>' + selectionPanel() + '</div>';
  }

  function manualForm() {
    return '<details class="m15-manual"' + (state.manualOpen ? ' open' : '') + ' id="m15-manual"><summary>找不到模型？手动添加</summary>' +
      '<div class="m15-manual-body"><label class="y15-field"><span>上游模型 ID</span><input class="y15-input" id="m15-mid" type="text" placeholder="例如 my-model-2026" autocomplete="off"></label>' +
      '<label class="y15-field"><span>协议</span><select class="y15-select" id="m15-mproto"><option>Chat Completions</option><option>Responses</option><option>Anthropic Messages</option></select></label>' +
      btn('添加并配置', 'manual', '', 'small primary') + '</div><p class="y15-small y15-muted">列表里没有的模型、服务没有模型列表接口时用。上下文窗口和最大输出补不全时，在「已选模型」那一行填写。</p></details>';
  }

  function selectBlock() {
    const on = state.phase === 'connected';
    return '<section class="m15-panel m15-flush"><div class="m15-models-head"><div class="m15-panel-head"><div class="m15-title"><span class="m15-num">2</span><h2>选择模型</h2></div>' +
      '<span class="y15-small y15-muted">勾选后自动配置，不用单独保存，也不用单独测试</span></div>' +
      '<label class="m15-search">' + ui.icon('search') + '<input id="m15-search" type="search" aria-label="搜索模型" placeholder="搜索模型名称、提供方或上游模型 ID" value="' + esc(state.search) + '" data-act="m15.search"' + (on ? '' : ' disabled') + '></label>' +
      '<div class="m15-filters" role="group" aria-label="筛选模型">' + [['auto', '可自动配置'], ['vision', '支持图像'], ['reasoning', '支持推理'], ['all', '全部模型'], ['selected', '已选用']].map(([id, l]) =>
        '<button type="button" class="m15-filter" data-act="m15.filter" data-filter="' + id + '" aria-pressed="' + (state.filter === id) + '"' + (on ? '' : ' disabled') + '>' + l + '</button>').join('') + '</div></div>' +
      results() + '<div class="m15-foot"><span>' + (on ? '来源：' + esc(state.savedUrl) + '/models · ' + esc(ui.time(Y15.app.now())) + ' 采集' : '获取完成后，按模型用途整理候选') + '</span><span>上下文、最大输出、协议自动填写</span></div>' + manualForm() + '</section>';
  }

  // ---------------------------------------------------------------- 区域四：高级（折叠）

  function advancedBlock() {
    const doc = JSON.stringify({
      connections: state.saved ? [{ id: hostOf(state.savedUrl), address: state.savedUrl, credential: 'HOST_KEY' }] : [],
      models: ready().map((r) => ({ connection: hostOf(state.savedUrl), upstream: r.id, protocol: r.protocol, window: r.context, max_output: r.output })),
      department_defaults: state.defaults
    }, null, 2);
    return '<details class="m15-adv"><summary>高级</summary><div class="m15-adv-body">' +
      '<h4 class="m15-sub">连接</h4>' + ui.kv([['ID 与名称', state.saved ? esc(hostOf(state.savedUrl)) + '（取地址的主机名，可以改）' : '连接之后生成'], ['凭据引用', state.saved ? ui.code('HOST_KEY') + '（可以改成引用环境变量）' : '连接之后生成'],
        ['模型列表地址', state.saved ? ui.code(state.savedUrl + '/models') : '默认是服务地址加 /models'], ['超时', '600 秒（按多久没收到新数据算，不按回复总时长）']], 'is-rows') +
      '<h4 class="m15-sub">各模型的协议、推理档位、输入方式与单价</h4><p class="y15-small y15-muted">在这里修改每个已启用模型的这些项；改协议或上游模型 ID 会使它的准入作废并重新验证。此原型不画这一部分。</p>' +
      '<h4 class="m15-sub">模型能力表</h4>' + ui.kv([['版本', '第 41 版'], ['快照日期', '2026-10-30'], ['来源', 'models.dev']], 'is-rows') +
      '<h4 class="m15-sub">目录文档</h4><pre class="y15-pre m15-json">' + esc(doc) + '</pre><div class="y15-row">' + btn('格式化', 'toast', 'data-t="已格式化（演示）"', 'small') + btn('复制', 'toast', 'data-t="已复制到剪贴板（演示）"', 'small') +
      btn('导入', 'toast', 'data-t="导入是演示，不读文件"', 'small') + btn('导出', 'toast', 'data-t="导出是演示，不写文件"', 'small') + btn('重新读取目录文件', 'toast', 'data-t="目录文件没有变化（演示）"', 'small') + '</div>' +
      '</div></details>';
  }

  function demoBlock() {
    return '<details class="m15-demo" id="m15-demo"' + (demoOpen ? ' open' : '') + '><summary>原型演示 · 切换失败情形 / 一键填入示例</summary><p class="y15-small m15-gap">这里控制演示条件，不连接真实的模型服务。容量、用时和验证结果都是示例。</p>' +
      '<div class="y15-row"><label for="m15-mode" class="y15-small">情形</label><select class="y15-select" id="m15-mode" data-act="m15.mode">' + Object.keys(MODES).map((id) => '<option value="' + id + '"' + (state.mode === id ? ' selected' : '') + '>' + MODES[id] + '</option>').join('') + '</select>' +
      btn('填入示例地址和 Key', 'example', '', 'small') + btn('重新开始', 'reset', '', 'small') + '</div>' +
      '<p class="y15-small y15-muted m15-gap">' + esc(DEMO_HELP[state.mode]) + '</p>' +
      '<div class="m15-demo-state"><span>连接：' + ({ idle: '待连接', connecting: '获取中', connected: '已连接', failed: '失败' })[state.phase] + '</span><span>已选用：' + rows().length + '</span><span>已启用：' + ready().length + '</span><span>部门使用：' +
      Object.values(state.defaults).filter(Boolean).length + '/3</span></div></details>';
  }
  const DEMO_HELP = {
    normal: '地址和 Key 随便填（例如点「填入示例」），获取到 139 个候选，其中 12 个是能自动配置的对话模型。',
    auth: '含 invalid 的 Key 会被拒绝（401）；改成别的 Key 就能继续。',
    network: '含 .invalid 的地址连不上；改成 https://api.example.com/v1 就能继续。',
    notlist: '地址里带 docs 的会返回一个网页而不是模型列表；去掉它就能继续。',
    path: '地址以 /chat/completions 结尾会得到 404；把地址填到它的上一级就能继续。',
    empty: '连接成功，服务没有返回任何模型；可以试「手动添加」。',
    test: '第一个对话模型（DeepSeek V4 Flash）验证时被拒绝，其他模型可以继续启用。',
    unknown: '候选里有一个模型没有给出容量，需要在「已选模型」里填写窗口和输出上限。'
  };

  function render() {
    const connected = state.phase === 'connected';
    const n = ready().length;
    return '<div class="m15"><div class="y15-page-head m15-head"><div class="y15-page-titles"><h1>模型管理</h1><p class="y15-muted">填好服务地址和 Key，参数自动补全，勾选后即可使用。</p></div>' +
      '<div class="y15-page-actions">' + btn('返回原界面', 'back', '', '') + '</div></div>' +
      '<div class="m15-flow" aria-label="配置进度"><span class="' + (connected ? 'is-done' : '') + '"><b>' + (connected ? '✓' : '1') + '</b>连接服务</span><i>→</i><span class="' + (n ? 'is-done' : '') + '"><b>' + (n ? '✓' : '2') + '</b>勾选模型</span><i>→</i><span class="' + (n ? 'is-done' : '') + '"><b>' + (n ? '✓' : '3') + '</b>部门使用</span></div>' +
      '<div class="m15-top">' + connectionBlock() + usageBlock() + '</div>' + selectBlock() + advancedBlock() + demoBlock() + '</div>';
  }

  // ---------------------------------------------------------------- 动作

  function failure() {
    const base = normalize(state.url);
    const req = base + '/models';
    if (state.mode === 'auth' && state.key.includes('invalid')) return { title: 'HTTP 401 · 服务拒绝了这个 API Key', url: req, detail: '不显示服务的回应内容，因为它可能带出 Key。', hint: '请修改 API Key 后再获取。' };
    if (state.mode === 'network' && base.includes('.invalid')) return { title: '连接失败 · 没有收到响应', url: req, detail: '原因：域名无法解析（超时和证书错误也会显示在这里）。', hint: '请修改服务地址，或检查网络后再获取。' };
    if (state.mode === 'notlist' && base.includes('docs')) return { title: '服务返回的不是模型列表', url: req, detail: '状态正常，但收到的内容类型是 text/html。', hint: '请检查服务地址是不是填成了文档页面。' };
    if (state.mode === 'path' && /\/chat\/completions$/.test(base)) return { title: 'HTTP 404 · 找不到这个地址', url: req, detail: '你填的地址以 /chat/completions 结尾。', hint: '请把地址填到它的上一级，例如去掉 /chat/completions。' };
    return null;
  }

  async function connect() {
    if (busy() || issue()) return;
    const url = normalize(state.url);
    const was = state.phase === 'connected';
    const changed = was && url !== state.savedUrl;
    const run = ++generation;
    state.url = url; state.phase = 'connecting'; state.error = null; redraw();
    await wait();
    if (run !== generation) return;
    const f = failure();
    if (f) { state.phase = was ? 'connected' : 'failed'; state.error = f; state.saved = state.saved || Boolean(state.key); redraw(); return; }
    state.savedUrl = url; state.phase = 'connected'; state.saved = true; state.key = ''; state.showKey = false; state.editing = false;
    state.candidates = state.mode === 'empty' ? [] : state.mode === 'unknown' ? [unknown, ...examples] : catalog;
    state.fetchedAt = Y15.app.now();
    if (!was) { state.filter = state.mode === 'unknown' ? 'all' : 'auto'; state.limit = 8; }
    // 地址变了：该连接下的准入作废，列表里仍有的已选模型自动重新验证，没有的标「不在新的模型列表中」
    if (changed) {
      Object.keys(state.selected).forEach((id) => {
        const inList = state.candidates.some((c) => c.id === id);
        if (inList) { state.selected[id].status = 'stale'; state.selected[id].error = null; retest(id); }
        else { state.selected[id].status = 'stale'; state.selected[id].error = '不在新的模型列表中。'; }
      });
    }
    redraw();
  }

  function retest(id) {
    const row = state.selected[id];
    if (!row) return;
    row.ticket = ++attempt; row.error = null; row.status = 'waiting';
    pump();
  }

  function pump() {
    rows().forEach((r) => {
      if (r.status !== 'waiting') return;
      if (rows().filter((x) => x.status === 'testing').length >= MAX_TEST) return;
      r.status = 'testing';
      runTest(r.id, r.ticket);
    });
    redraw();
  }

  async function runTest(id, ticket) {
    const run = generation;
    const cur = () => run === generation && state.selected[id] && state.selected[id].ticket === ticket;
    await wait(900);
    if (!cur()) { pump(); return; }
    const row = state.selected[id];
    if (state.mode === 'test' && id === examples[0].id) {
      Object.assign(row, { status: 'failed', error: '最小问答未通过：HTTP 403，当前 Key 没有调用这个模型的权限。请重新验证、修改 Key，或取消选用后另选模型。' });
    } else {
      Object.assign(row, { status: 'ready', error: null, took: (2 + (id.length % 5) / 2).toFixed(1) });
      // 第一个通过的模型，成为还没有部门使用的部门的默认
      Object.keys(DEPTS).forEach((d) => { if (!state.defaults[d]) state.defaults[d] = id; });
    }
    pump();
  }

  async function configure(id) {
    const model = state.candidates.find((c) => c.id === id);
    if (!model) return;
    const ticket = ++attempt;
    const run = generation;
    state.notice = '';
    state.selected[id] = Object.assign({}, model, { status: 'metadata', ticket, error: null });
    redraw();
    await wait();
    if (run !== generation || !state.selected[id] || state.selected[id].ticket !== ticket) return;
    if (model.context === null || model.output === null) {
      Object.assign(state.selected[id], { status: 'unknown', error: '上游模型列表和模型能力表都没有给出' + (model.context === null && model.output === null ? '上下文窗口和最大输出' : model.context === null ? '上下文窗口' : '最大输出') + '，暂时不能验证。请在下面填写，或取消选用。' });
      redraw(); return;
    }
    state.selected[id].status = 'waiting';
    pump();
  }

  function remove(id) {
    const refs = refsOf(id);
    if (refs.length) { state.notice = '不能取消选用「' + (state.selected[id] ? state.selected[id].name : id) + '」：它被' + refs.join('、') + '使用。先在「部门使用」里换成别的模型，再取消。'; redraw(); return; }
    state.notice = '';
    delete state.selected[id];
    redraw();
  }

  function mount(ctx, root) {
    const form = root.querySelector('#m15-form');
    if (!form) return;
    form.addEventListener('submit', (e) => { e.preventDefault(); connect(); });
    const hint = () => {
      const p = issue();
      const b = root.querySelector('#m15-connect');
      if (b) b.disabled = Boolean(p) || busy();
      const h = root.querySelector('#m15-hint');
      if (h) h.textContent = p || '填好了，可以获取模型。';
    };
    root.querySelector('#m15-url').addEventListener('input', (e) => { state.url = e.target.value; hint(); });
    root.querySelector('#m15-key').addEventListener('input', (e) => { state.key = e.target.value; hint(); });
  }

  Y15.readyModels = () => ready().map((r) => r.name);
  Y15.views.register('sys-models', { render, mount });

  const A = (name, fn) => Y15.actions.register('m15.' + name, fn);
  A('showKey', () => { state.showKey = !state.showKey; redraw(); });
  A('connect', connect);
  A('edit', () => { state.editing = true; redraw(); const u = document.getElementById('m15-url'); if (u) u.focus(); });
  A('delete', () => {
    const referenced = ready().filter((r) => refsOf(r.id).length);
    if (referenced.length) {
      ui.modal({ title: '不能删除这个连接', body: '<p>它下面的模型还被引用着：</p><ul class="y15-list">' + referenced.map((r) => '<li>' + esc(r.name) + '：' + esc(refsOf(r.id).join('、')) + '</li>').join('') + '</ul><p class="y15-muted">先在「部门使用」里换成别的模型，或设为「未设置」。</p>', actions: [{ label: '知道了', close: true }] });
      return;
    }
    ui.modal({ title: '删除这个连接', body: '<p>将一起删除：</p><ul class="y15-list"><li>连接 ' + esc(state.savedUrl) + '</li><li>它保存的 API Key</li><li>已选用的 ' + rows().length + ' 个模型</li></ul>', actions: [{ label: '确认删除', kind: 'primary danger', act: 'm15.delete-ok', close: true }, { label: '取消', close: true }] });
  });
  A('delete-ok', () => { generation += 1; state = initial(state.mode); redraw(); });
  A('search', (el) => { state.search = el.value; state.limit = 8; redraw(); });
  A('filter', (el) => { state.filter = el.dataset.filter; state.limit = 8; redraw(); });
  A('clear', () => { state.search = ''; state.filter = 'all'; state.limit = 8; redraw(); });
  A('more', () => { state.limit += 12; redraw(); });
  A('pick', (el) => { const id = el.dataset.id; if (state.selected[id]) remove(id); else configure(id); });
  A('remove', (el) => remove(el.dataset.id));
  A('retry', (el) => retest(el.dataset.id));
  A('fill', (el) => {
    const id = el.dataset.id;
    const w = Number(document.getElementById('m15-win-' + id).value) * 1000;
    const o = Number(document.getElementById('m15-out-' + id).value) * 1000;
    const row = state.selected[id];
    if (!(w > 0) || !(o > 0)) { row.error = '窗口和最大输出都要填，并且大于 0。'; redraw(); return; }
    if (o > w) { row.error = '最大输出不能大于上下文窗口。'; redraw(); return; }
    Object.assign(row, { context: w, output: o, source: '手动填写', error: null });
    retest(id);
  });
  A('manual', () => {
    const id = document.getElementById('m15-mid').value.trim();
    const proto = document.getElementById('m15-mproto').value;
    if (!id) { ui.toast('先填上游模型 ID', 'warn'); return; }
    if (!state.candidates.some((c) => c.id === id)) state.candidates = [Object.assign({}, unknown, { id, name: id, provider: '手动添加', protocol: proto, source: '手动添加' }), ...state.candidates];
    state.manualOpen = true;
    configure(id);
  });
  A('department', (el) => { state.defaults[el.dataset.department] = el.value; if (!el.value) state.levels[el.dataset.department] = ''; redraw(); ui.toast('已保存，从下一次模型请求起生效', 'ok'); });
  A('level', (el) => { state.levels[el.dataset.department] = el.value; redraw(); });
  A('role', (el) => { if (el.value) state.roles[el.dataset.key] = el.value; else delete state.roles[el.dataset.key]; redraw(); });
  A('mode', (el) => { generation += 1; demoOpen = true; state = initial(el.value); redraw(); });
  A('example', () => {
    const m = state.mode;
    state.url = m === 'network' ? 'https://unreachable.invalid/v1' : m === 'notlist' ? 'https://api.example.com/docs' : m === 'path' ? 'https://api.example.com/v1/chat/completions' : 'https://api.example.com/v1';
    state.key = m === 'auth' ? 'example-key-invalid' : 'example-key-for-prototype';
    state.editing = true; demoOpen = true; redraw();
  });
  A('reset', () => { generation += 1; demoOpen = true; state = initial(state.mode); redraw(); });
  A('toast', (el) => ui.toast(el.dataset.t, 'ok'));
  A('back', () => { const b = Y15.state.back || '#/home'; Y15.go(b); });
})();
