// 设置（设计说明第 7.5 节）：基本信息、部门设置、登记命令、源目录、工具授权（3.2B）、机器授权与执行位置（3.2C）、运维（Stage 4）、角色设置（Stage 5）
(function () {
  'use strict';
  const Y9 = window.Y9;
  const esc = Y9.esc;
  const ui = Y9.ui;

  const DEPTS = ['product', 'engineering', 'quality', 'operations'];
  const LABELS = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const REASONING_LEVELS = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
  const PLACE_LABELS = { local_process: '本机进程', local_container: '本机容器' };

  const st = { form: null };

  function rerender() {
    Y9.app.renderContent(true);
  }

  function settings(ctx) {
    return Y9.api.query('project.settings', { project: ctx.projectId }).data;
  }

  function machines() {
    if (!Y9.cap.query('machines.list')) return null;
    return Y9.api.query('machines.list', {}).data;
  }

  function catalog() {
    if (!Y9.cap.query('catalog')) return null;
    return Y9.api.query('catalog', {}).data;
  }

  function lines(text) {
    return String(text || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  }

  function machineName(list, id) {
    const found = list ? list.find((machine) => machine.id === id) : null;
    return found ? found.name : id;
  }

  // ---------------------------------------------------------------------------
  // 区块

  function basicBlock(s) {
    const canRename = Y9.cap.command('project.rename');
    const canPin = Y9.cap.command('project.pin');
    const canArchive = Y9.cap.command('project.archive');
    const canRestore = Y9.cap.command('project.restore');
    const nameRow = canRename
      ? '<label class="y9-field"><span>名称</span><div class="y9-set-inline"><input class="y9-input" type="text" id="y9-set-name" value="' + esc(s.project.name) + '"' + (s.project.archived ? ' readonly' : '') + '>' +
        ui.button({ label: '重命名', act: 'set.rename', disabled: s.project.archived }) + '</div></label>'
      : '<div class="y9-field"><span>名称</span><div class="y9-set-stack"><strong>' + esc(s.project.name) + '</strong></div></div>';
    const pinRow = '<div class="y9-field"><span>置顶</span><div class="y9-set-inline">' + (s.project.pinned ? ui.status('done', '已置顶') : '<span class="y9-muted">未置顶</span>') +
      (canPin ? ui.button({ label: s.project.pinned ? '取消置顶' : '置顶', kind: 'small', cmd: 'project.pin', data: { project: s.project.id, pinned: String(!s.project.pinned), base_version: s.project.version } }) : '') + '</div></div>';
    const archiveRow = '<div class="y9-field"><span>归档</span><div class="y9-set-inline">' + (s.project.archived ? ui.status('cancelled', '已归档') : '<span class="y9-muted">未归档</span>') +
      (s.project.archived
        ? (canRestore ? ui.button({ label: '恢复项目', kind: 'small primary', cmd: 'project.restore', data: { project: s.project.id, base_version: s.project.version } }) : '')
        : (canArchive ? ui.button({ label: '归档', kind: 'small danger', cmd: 'project.archive', data: { project: s.project.id, base_version: s.project.version } }) : '')) + '</div></div>';
    const body = '<div class="y9-set-basic">' + nameRow +
      '<div class="y9-field"><span>长期目标</span><p class="y9-set-goal">' + esc(s.project.goal || '尚未填写') + '</p></div>' +
      pinRow + archiveRow + '</div>' +
      (s.project.archived ? ui.note('归档只读：查询仍可用，写命令会返回冲突。', 'warn') : '');
    return ui.block({ title: '基本信息', query: 'project.settings', body: body });
  }

  function deptCard(ctx, s, department) {
    const entry = s.departments[department];
    const resolved = entry.resolved || {};
    const promptLabel = entry.prompt_text ? '配置 v' + entry.prompt_version : '默认 v0';
    const preview = entry.prompt_text ? entry.prompt_text : '内置默认 Prompt';
    const rows = [
      ['模型', (entry.model ? '' : '<small class="y9-muted y9-block-line">跟随部门默认</small>') +
        (resolved.definition ? '<span class="y9-set-stack"><strong>' + esc(resolved.label) + '</strong><small class="y9-muted">来源：' + esc(resolved.source || '—') + '</small>' +
          (resolved.problem ? ui.status('unusable', '无法使用：' + resolved.problem) : ui.status('admitted', '已准入')) + '</span>' : ui.status('idle', '未设置'))],
      ['推理档位', resolved.definition ? esc((resolved.request_level ? '请求 ' + resolved.request_level : '请求档位为空（模型默认）') + ' · 发送 ' + (resolved.sent_level || '不带推理参数')) : ''],
      ['部门 Prompt', ui.tag(promptLabel) + '<small class="y9-muted y9-block-line y9-set-clip">' + esc(preview) + '</small>'],
      ['设置版本', entry.version ? ui.code('v' + entry.version) : '<span class="y9-muted">尚未写入，全部跟随</span>']
    ];
    return '<article class="y9-set-dept' + (department === 'operations' ? ' is-ops' : '') + '">' +
      '<header><h3>' + esc(LABELS[department]) + '部门</h3>' + (department === 'operations' ? ui.tag('Stage 4') : '') + '</header>' +
      ui.kv(rows, 'is-rows') +
      '<div class="y9-row">' + ui.button({ label: '编辑部门设置', kind: 'small', act: 'dept.openSettings', data: { project: s.project.id, department: department } }) + '</div></article>';
  }

  function deptBlock(ctx, s) {
    const cards = DEPTS.filter((department) => s.departments[department]).map((department) => deptCard(ctx, s, department)).join('');
    return ui.block({
      title: '部门设置', query: 'project.settings', command: 'department_settings.save',
      subtitle: '本项目各部门的项目部门设置，内容同部门设置弹窗；没有写入的项跟随部门默认，不修改部门默认。',
      body: '<div class="y9-set-depts">' + cards + '</div>'
    });
  }

  function commandForm(s) {
    const f = st.form;
    const current = f.mode === 'edit' ? s.commands.find((entry) => entry.name === f.name) : null;
    if (f.mode === 'edit' && !current) throw new Error('找不到登记命令：' + f.name);
    const key = 'set.cmd.' + s.project.id + '.' + (f.mode === 'edit' ? f.name : 'new') + '.';
    const base = current || { name: '', argv: '', args: [], timeout_sec: 60, output_limit: 200000 };
    const argvText = Array.isArray(base.argv) ? base.argv.join('\n') : String(base.argv || '');
    return '<div class="y9-set-form" id="y9-set-cmd-form"><h3 class="y9-h3">' + (f.mode === 'edit' ? '修改登记命令「' + esc(f.name) + '」 · 基于 v' + esc(f.base_version) : '新增登记命令') + '</h3>' +
      '<div class="y9-set-form-grid">' +
      '<label class="y9-field"><span>登记名</span><input class="y9-input" type="text" id="y9-set-cmd-name" value="' + esc(base.name) + '"' + (f.mode === 'edit' ? ' readonly' : ' data-draft="' + esc(key + 'name') + '"') + ' placeholder="例如 unit_tests"><small class="y9-muted">小写字母、数字与下划线</small></label>' +
      '<label class="y9-field"><span>时限（秒）</span><input class="y9-input" type="number" min="1" id="y9-set-cmd-timeout" value="' + esc(base.timeout_sec) + '" data-draft="' + esc(key + 'timeout') + '"></label>' +
      '<label class="y9-field"><span>输出上限（字节）</span><input class="y9-input" type="number" min="1" id="y9-set-cmd-limit" value="' + esc(base.output_limit) + '" data-draft="' + esc(key + 'limit') + '"></label>' +
      '<label class="y9-field y9-set-wide"><span>固定参数（每行一个）</span><textarea class="y9-textarea y9-set-mono" rows="4" id="y9-set-cmd-argv" data-draft="' + esc(key + 'argv') + '">' + esc(argvText) + '</textarea></label>' +
      '<label class="y9-field y9-set-wide"><span>允许的额外参数（每行一个）</span><textarea class="y9-textarea y9-set-mono" rows="3" id="y9-set-cmd-args" data-draft="' + esc(key + 'args') + '">' + esc((base.args || []).join('\n')) + '</textarea><small class="y9-muted">模型只能在这些参数中选择；私有路径与越界参数会被拒绝。</small></label>' +
      '</div>' +
      '<div class="y9-row">' + ui.button({ label: '保存', kind: 'primary', act: 'set.saveCommand' }) + ui.button({ label: '取消', act: 'set.cancelCommand' }) + '</div></div>';
  }

  function commandsBlock(s) {
    const argvText = (row) => (Array.isArray(row.argv) ? row.argv.join(' ') : String(row.argv || ''));
    const table = ui.table({
      columns: [
        { key: 'name', label: '登记名', render: (row) => ui.code(row.name) },
        { key: 'argv', label: '固定参数', render: (row) => ui.code(argvText(row)) },
        { key: 'args', label: '允许的额外参数', render: (row) => (row.args && row.args.length ? row.args.map((arg) => ui.code(arg)).join(' ') : '<span class="y9-muted">不允许</span>') },
        { key: 'timeout_sec', label: '时限', render: (row) => esc(row.timeout_sec + ' 秒') },
        { key: 'output_limit', label: '输出上限', render: (row) => esc(Y9.ui.num(row.output_limit) + ' 字节') },
        { key: 'version', label: '版本', render: (row) => ui.code('v' + row.version) },
        { key: 'ops', label: '操作', className: 'y9-col-actions', render: (row) => ui.button({ label: '修改', kind: 'small', act: 'set.editCommand', data: { name: row.name }, disabled: s.project.archived }) }
      ],
      rows: s.commands,
      empty: '本项目还没有登记命令'
    });
    return ui.block({
      title: '登记命令', query: 'project.settings', command: 'command_registration.save',
      subtitle: '部门只能执行这里登记的命令：固定参数不可改，额外参数只能从允许的列表中选；版本冲突时提示重新读取。',
      actions: st.form ? '' : ui.button({ label: '新增登记命令', icon: 'plus', kind: 'small', act: 'set.addCommand', disabled: s.project.archived }),
      body: table + (st.form && st.form.project_id === s.project.id ? commandForm(s) : '')
    });
  }

  function sourceBlock(s) {
    const store = s.source_directories;
    const table = store.items.length
      ? ui.table({
        columns: [
          { key: 'name', label: '名称', render: (row) => ui.code(row.name) },
          { key: 'path', label: '路径', render: (row) => '<span class="y9-set-url">' + esc(row.path) + '</span>' }
        ],
        rows: store.items
      })
      : ui.empty('还没有登记源目录');
    const form = '<div class="y9-set-form"><h3 class="y9-h3">登记源目录 · 基于 v' + esc(store.version) + '</h3>' +
      '<div class="y9-set-form-grid">' +
      '<label class="y9-field"><span>名称</span><input class="y9-input" type="text" id="y9-set-src-name" placeholder="例如 webapp" data-draft="set.src.name"></label>' +
      '<label class="y9-field y9-set-wide"><span>路径</span><input class="y9-input y9-set-mono" type="text" id="y9-set-src-path" placeholder="/work/webapp 或服务所在机器上的绝对路径" data-draft="set.src.path"></label>' +
      '</div><div class="y9-row">' + ui.button({ label: '保存源目录', kind: 'primary', act: 'set.saveSource', disabled: s.project.archived }) +
      '<small class="y9-muted">新建事项时可以选择登记过的源目录作为代码快照来源。</small></div></div>';
    return ui.block({
      title: '源目录', query: 'project.settings', command: 'source_directory.save',
      subtitle: '新建事项的代码快照来源；同名登记覆盖原路径，版本加一。',
      body: table + form
    });
  }

  function toolsBlock(s) {
    if (!s.tools) return '';
    const rows = s.tools.map((tool) => {
      return '<div class="y9-set-dept" data-tool-id="' + esc(tool.id) + '"><header><h3>' + esc(tool.label) + '</h3>' + ui.tag(tool.id) + '</header>' +
        '<label class="y9-field"><span>授权范围</span><input class="y9-input" type="text" data-tool-scope value="' + esc(tool.scope) + '">' +
        '<small class="y9-muted">例如允许取回的域名；不授权时写「未授权」。</small></label>' +
        '<label class="y9-field"><span>批准方式</span><input class="y9-input" type="text" data-tool-approval value="' + esc(tool.approval || '') + '" placeholder="超出范围时逐次批准"></label>' +
        '</div>';
    }).join('');
    return ui.block({
      title: '工具授权', query: 'project.settings', command: 'tool_authorization.save',
      subtitle: '网络取回与各 MCP 工具在本项目的授权范围；超出授权时逐次批准，批准一次不作为永久授权。当前版本 v' + esc(s.tools_version) + '。',
      body: '<div class="y9-set-depts">' + rows + '</div>' +
        '<div class="y9-row">' + ui.button({ label: '保存工具授权', kind: 'primary', act: 'set.saveTools', disabled: s.project.archived }) + '</div>'
    });
  }

  function machineRow(list, s, machine) {
    const auth = s.machines.find((entry) => entry.machine_id === machine.id);
    return '<div class="y9-set-dept" data-machine-id="' + esc(machine.id) + '"><header><h3>' + esc(machine.name) + '</h3>' +
      '<label class="y9-field is-inline"><input type="checkbox" data-machine-use' + (auth ? ' checked' : '') + '><span>授权使用</span></label></header>' +
      '<p class="y9-muted y9-small">' + esc(machine.address) + ' · ' + esc(machine.purpose || '') + (machine.online ? '' : ' · 离线') + '</p>' +
      '<label class="y9-field"><span>登记的目录（每行一个）</span><textarea class="y9-textarea y9-set-mono" rows="2" data-machine-dirs>' + esc((auth && auth.dirs ? auth.dirs : []).join('\n')) + '</textarea></label>' +
      '<label class="y9-field"><span>可以执行的操作（每行一个）</span><textarea class="y9-textarea y9-set-mono" rows="2" data-machine-ops>' + esc((auth && auth.operations ? auth.operations : []).join('\n')) + '</textarea></label>' +
      (Y9.cap.query('ops.status')
        ? '<label class="y9-field is-inline"><input type="checkbox" data-machine-runtime' + (auth && auth.runtime_env ? ' checked' : '') + '><span>作为运行环境</span></label>' +
          '<label class="y9-field"><span>常设授权清单（每行一个）</span><textarea class="y9-textarea y9-set-mono" rows="2" data-machine-standing>' + esc((auth && auth.standing ? auth.standing : []).join('\n')) + '</textarea></label>'
        : '') +
      '</div>';
  }

  function machinesBlock(s) {
    const list = machines();
    if (!list) return ui.empty('系统页的机器查询还没有登记');
    const rows = list.map((machine) => machineRow(list, s, machine)).join('');
    return ui.block({
      title: '机器授权', query: ['project.settings', 'machines.list'], command: 'machine_authorization.save',
      subtitle: '从系统登记的机器中选择本项目可以使用的机器，每台写明登记的目录与可以执行的操作；Stage 4 起可以指定为本项目的运行环境并批准常设授权清单。当前版本 v' + esc(s.machines_version) + '。',
      body: '<div class="y9-set-depts">' + rows + '</div>' +
        '<div class="y9-row">' + ui.button({ label: '保存机器授权', kind: 'primary', act: 'set.saveMachines', disabled: s.project.archived }) + '</div>'
    });
  }

  function placementOptions(list, current, extraLabel) {
    const options = ['<option value=""' + (current ? '' : ' selected') + '>' + esc(extraLabel) + '</option>',
      '<option value="local_process"' + (current === 'local_process' ? ' selected' : '') + '>' + esc(PLACE_LABELS.local_process) + '</option>',
      '<option value="local_container"' + (current === 'local_container' ? ' selected' : '') + '>' + esc(PLACE_LABELS.local_container) + '</option>'];
    (list || []).forEach((machine) => {
      options.push('<option value="' + esc(machine.id) + '"' + (current === machine.id ? ' selected' : '') + '>' + esc(machine.name) + '</option>');
    });
    return options.join('');
  }

  function placementBlock(s) {
    const list = machines();
    if (!list) return '';
    const place = s.execution_placement;
    const checks = place.checks || {};
    const checkRow = (department) => '<label class="y9-field"><span>' + esc(LABELS[department]) + '的检查</span>' +
      '<select class="y9-select" data-place-check="' + department + '">' + placementOptions(list, checks[department] || '', '与运行工作区相同') + '</select></label>';
    return ui.block({
      title: '执行位置', query: ['project.settings', 'machines.list'], command: 'execution_placement.save',
      subtitle: '运行工作区的位置、产品·工程·质检各自检查的位置与容器基础镜像；位置是登记的机器时，它必须在本项目的机器授权中。当前版本 v' + esc(place.version) + '。',
      body: '<div class="y9-set-form-grid">' +
        '<label class="y9-field"><span>运行工作区</span><select class="y9-select" id="y9-set-place-workspace">' + placementOptions(list, place.workspace, '本机进程') + '</select></label>' +
        checkRow('product') + checkRow('engineering') + checkRow('quality') +
        '<label class="y9-field y9-set-wide"><span>容器基础镜像（可选）</span><input class="y9-input y9-set-mono" type="text" id="y9-set-place-image" value="' + esc(place.image || '') + '" placeholder="留空使用 Yudao 默认基础镜像"></label>' +
        '</div><div class="y9-row">' + ui.button({ label: '保存执行位置', kind: 'primary', act: 'set.savePlacement', disabled: s.project.archived }) + '</div>'
    });
  }

  function opsBlock(s) {
    if (!s.ops) return '';
    return ui.block({
      title: '运维', query: 'project.settings',
      subtitle: '观察窗口与同一故障连续修复失败的次数上限；由运维工作的工单配置，这里只读显示。',
      body: ui.kv([
        ['观察窗口', esc(s.ops.observe_hours + ' 小时')],
        ['连续修复失败次数上限', esc(s.ops.max_repair_failures + ' 次')]
      ])
    });
  }

  function rolesBlock(s) {
    if (!s.roles) return '';
    const cat = catalog();
    const admitted = cat ? cat.admitted : [];
    const sections = DEPTS.filter((department) => s.roles[department]).map((department) => {
      const rows = s.roles[department].map((role) => {
        const options = ['<option value=""' + (role.model ? '' : ' selected') + '>跟随角色默认</option>'].concat(admitted.map((def) =>
          '<option value="' + esc(def.id) + '"' + (def.id === role.model ? ' selected' : '') + '>' + esc(def.label || def.upstream_model || def.id) + '</option>'
        )).join('');
        const levels = ['<option value=""' + (role.request_level ? '' : ' selected') + '>跟随模型默认</option>'].concat(REASONING_LEVELS.map((level) =>
          '<option value="' + level + '"' + (level === role.request_level ? ' selected' : '') + '>' + esc(level) + '</option>'
        )).join('');
        return '<div class="y9-dm-role" data-role-id="' + esc(role.role_id) + '">' +
          '<div class="y9-dm-role-name"><strong>' + esc(role.name || role.role_id) + '</strong><small class="y9-muted">' + esc(role.duty || '') + '</small></div>' +
          '<label class="y9-field"><span>模型</span><select class="y9-select" data-role-model>' + options + '</select></label>' +
          '<label class="y9-field"><span>推理档位</span><select class="y9-select" data-role-level>' + levels + '</select></label>' +
          '<label class="y9-field y9-dm-role-prompt"><span>角色 Prompt</span><textarea class="y9-textarea" rows="2" data-role-prompt placeholder="空为内置默认">' + esc(role.prompt_text || '') + '</textarea></label>' +
          '</div>';
      }).join('');
      return '<section class="y9-set-roles" data-roles-dept="' + esc(department) + '"><div class="y9-set-roles-head"><h3 class="y9-h3">' + esc(LABELS[department]) + '部门</h3>' +
        ui.tag('Stage 5') + '</div><div class="y9-dm-roles">' + rows + '</div>' +
        '<div class="y9-row">' + ui.button({ label: '保存' + esc(LABELS[department]) + '部门的角色设置', kind: 'primary small', act: 'set.saveRoles', data: { department: department }, disabled: s.project.archived }) +
        '<small class="y9-muted">从这些角色下一次模型请求起生效。</small></div></section>';
    }).join('');
    return ui.block({
      title: '本项目各角色设置', query: 'project.settings', command: 'role_settings.save',
      subtitle: '解析顺序：项目角色设置、角色默认、项目部门设置、部门默认，取第一个写入了的。当前版本 v' + esc(s.roles_version) + '。',
      body: sections
    });
  }

  // ---------------------------------------------------------------------------
  // 页面与动作

  function render(ctx) {
    const s = settings(ctx);
    if (st.form && st.form.project_id !== s.project.id) st.form = null;
    return '<div class="y9-set">' +
      '<header class="y9-page-head"><div class="y9-page-titles"><p class="y9-eyebrow">项目设置</p><h1>' + esc(s.project.name) + '</h1>' +
      '<p class="y9-subtitle">基本信息、部门设置、登记命令、源目录、工具授权、机器授权、执行位置与角色设置。</p></div></header>' +
      basicBlock(s) + deptBlock(ctx, s) + commandsBlock(s) + sourceBlock(s) + toolsBlock(s) + machinesBlock(s) + placementBlock(s) + opsBlock(s) + rolesBlock(s) +
      '</div>';
  }

  Y9.views.register('settings', {
    title: () => '设置',
    needs: { queries: ['project.settings'] },
    render: render
  });

  Y9.actions.register('set.rename', () => {
    const ctx = Y9.app.ctx();
    const s = settings(ctx);
    const input = document.getElementById('y9-set-name');
    const name = input ? input.value.trim() : '';
    if (!name) {
      Y9.ui.toast('名称不能为空', 'warn');
      return;
    }
    Y9.run('project.rename', { project: ctx.projectId, name: name, base_version: s.project.version });
  });

  Y9.actions.register('set.addCommand', () => {
    const ctx = Y9.app.ctx();
    st.form = { project_id: ctx.projectId, mode: 'add', name: null, base_version: null };
    rerender();
  });

  Y9.actions.register('set.editCommand', (el) => {
    const ctx = Y9.app.ctx();
    const s = settings(ctx);
    const command = s.commands.find((entry) => entry.name === el.dataset.name);
    if (!command) throw new Error('找不到登记命令：' + el.dataset.name);
    st.form = { project_id: ctx.projectId, mode: 'edit', name: command.name, base_version: command.version };
    rerender();
  });

  Y9.actions.register('set.cancelCommand', () => {
    st.form = null;
    rerender();
  });

  Y9.actions.register('set.saveCommand', () => {
    const f = st.form;
    if (!f) return;
    const nameEl = document.getElementById('y9-set-cmd-name');
    const argvEl = document.getElementById('y9-set-cmd-argv');
    const argsEl = document.getElementById('y9-set-cmd-args');
    const timeoutEl = document.getElementById('y9-set-cmd-timeout');
    const limitEl = document.getElementById('y9-set-cmd-limit');
    const result = Y9.run('command_registration.save', {
      project: f.project_id,
      name: nameEl.value.trim(),
      argv: lines(argvEl.value),
      args: lines(argsEl.value),
      timeout_sec: Number(timeoutEl.value),
      output_limit: Number(limitEl.value),
      base_version: f.base_version === null ? 0 : f.base_version
    });
    if (!result.accepted) return;
    st.form = null;
    rerender();
  });

  Y9.actions.register('set.saveSource', () => {
    const ctx = Y9.app.ctx();
    const s = settings(ctx);
    const name = document.getElementById('y9-set-src-name');
    const path = document.getElementById('y9-set-src-path');
    const result = Y9.run('source_directory.save', {
      project: ctx.projectId,
      name: name ? name.value.trim() : '',
      path: path ? path.value.trim() : '',
      base_version: s.source_directories.version
    });
    if (!result.accepted) return;
    Y9.app.clearDraft('set.src.name');
    Y9.app.clearDraft('set.src.path');
    rerender();
  });

  Y9.actions.register('set.saveTools', () => {
    const ctx = Y9.app.ctx();
    const s = settings(ctx);
    const rows = Array.prototype.slice.call(document.querySelectorAll('[data-tool-id]'));
    const tools = rows.map((row) => ({
      id: row.dataset.toolId,
      scope: row.querySelector('[data-tool-scope]').value.trim(),
      approval: row.querySelector('[data-tool-approval]').value.trim()
    }));
    const result = Y9.run('tool_authorization.save', { project: ctx.projectId, tools: tools, base_version: s.tools_version });
    if (!result.accepted) return;
    rerender();
  });

  Y9.actions.register('set.saveMachines', () => {
    const ctx = Y9.app.ctx();
    const s = settings(ctx);
    const rows = Array.prototype.slice.call(document.querySelectorAll('[data-machine-id]'));
    const list = rows.filter((row) => row.querySelector('[data-machine-use]').checked).map((row) => {
      const entry = {
        machine_id: row.dataset.machineId,
        dirs: lines(row.querySelector('[data-machine-dirs]').value),
        operations: lines(row.querySelector('[data-machine-ops]').value)
      };
      if (Y9.cap.query('ops.status')) {
        entry.runtime_env = row.querySelector('[data-machine-runtime]').checked;
        entry.standing = lines(row.querySelector('[data-machine-standing]').value);
      }
      return entry;
    });
    const result = Y9.run('machine_authorization.save', { project: ctx.projectId, machines: list, base_version: s.machines_version });
    if (!result.accepted) return;
    rerender();
  });

  Y9.actions.register('set.savePlacement', () => {
    const ctx = Y9.app.ctx();
    const s = settings(ctx);
    const value = (selector) => {
      const el = document.querySelector(selector);
      return el && el.value ? el.value : null;
    };
    const check = (department) => value('[data-place-check="' + department + '"]');
    const result = Y9.run('execution_placement.save', {
      project: ctx.projectId,
      workspace: value('#y9-set-place-workspace'),
      checks: { product: check('product'), engineering: check('engineering'), quality: check('quality') },
      image: value('#y9-set-place-image'),
      base_version: s.execution_placement.version
    });
    if (!result.accepted) return;
    rerender();
  });

  Y9.actions.register('set.saveRoles', (el) => {
    const ctx = Y9.app.ctx();
    const s = settings(ctx);
    const department = el.dataset.department;
    const section = document.querySelector('[data-roles-dept="' + department + '"]');
    if (!section) throw new Error('找不到角色设置区块：' + department);
    const roles = Array.prototype.slice.call(section.querySelectorAll('[data-role-id]')).map((row) => ({
      role_id: row.dataset.roleId,
      model: row.querySelector('[data-role-model]').value || null,
      request_level: row.querySelector('[data-role-level]').value || null,
      prompt_text: row.querySelector('[data-role-prompt]').value.trim() || null
    }));
    const result = Y9.run('role_settings.save', { project: ctx.projectId, department: department, roles: roles, base_version: s.roles_version });
    if (!result.accepted) return;
    rerender();
  });
})();
