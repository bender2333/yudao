// 设置（设计说明第 7.5 节）：基本信息、部门设置、源目录与成果写回（3.8）、机器授权与执行位置（3.2C）、运维（Stage 4）、角色设置（Stage 5）。
// 命令按函数直接执行、网络取回可以取回任意地址（ADR-0038），设置页没有「登记命令」与「工具授权」；MCP 服务器一节按网络取回与 MCP 工具设计说明第 11.1 节的文字实施，原型不画
(function () {
  'use strict';
  const Y13 = window.Y13;
  const esc = Y13.esc;
  const ui = Y13.ui;

  const DEPTS = ['product', 'engineering', 'quality', 'operations'];
  const LABELS = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const REASONING_LEVELS = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
  // 执行位置只有本机进程与授权的机器（ADR-0022：不使用容器）
  const PLACE_LABELS = { local_process: '本机进程' };

  function rerender() {
    Y13.app.renderContent(true);
  }

  function settings(ctx) {
    return Y13.api.query('project.settings', { project: ctx.projectId }).data;
  }

  function machines() {
    if (!Y13.cap.query('machines.list')) return null;
    return Y13.api.query('machines.list', {}).data;
  }

  function catalog() {
    if (!Y13.cap.query('catalog')) return null;
    return Y13.api.query('catalog', {}).data;
  }

  function lines(text) {
    return String(text || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  }

  // ---------------------------------------------------------------------------
  // 区块

  function basicBlock(s) {
    const canRename = Y13.cap.command('project.rename');
    const canPin = Y13.cap.command('project.pin');
    const canArchive = Y13.cap.command('project.archive');
    const canRestore = Y13.cap.command('project.restore');
    const nameRow = canRename
      ? '<label class="y13-field"><span>名称</span><div class="y13-set-inline"><input class="y13-input" type="text" id="y13-set-name" value="' + esc(s.project.name) + '"' + (s.project.archived ? ' readonly' : '') + '>' +
        ui.button({ label: '重命名', act: 'set.rename', disabled: s.project.archived }) + '</div></label>'
      : '<div class="y13-field"><span>名称</span><div class="y13-set-stack"><strong>' + esc(s.project.name) + '</strong></div></div>';
    // 长期目标可以修改（project.set_goal）：之后开始的事项使用新目标
    const goalRow = Y13.cap.command('project.set_goal')
      ? '<label class="y13-field"><span>长期目标</span><div class="y13-set-stack"><textarea class="y13-textarea" rows="3" id="y13-set-goal"' + (s.project.archived ? ' readonly' : '') + '>' + esc(s.project.goal || '') + '</textarea>' +
        '<div class="y13-set-inline">' + ui.button({ label: '保存长期目标', kind: 'small', act: 'set.goal', disabled: s.project.archived }) +
        '<small class="y13-muted">进行中的事项不受影响；之后开始的事项使用新目标。</small></div></div></label>'
      : '<div class="y13-field"><span>长期目标</span><p class="y13-set-goal">' + esc(s.project.goal || '尚未填写') + '</p></div>';
    const pinRow = '<div class="y13-field"><span>置顶</span><div class="y13-set-inline">' + (s.project.pinned ? ui.status('done', '已置顶') : '<span class="y13-muted">未置顶</span>') +
      (canPin ? ui.button({ label: s.project.pinned ? '取消置顶' : '置顶', kind: 'small', cmd: 'project.pin', data: { project: s.project.id, pinned: String(!s.project.pinned), base_version: s.project.version } }) : '') + '</div></div>';
    const archiveRow = '<div class="y13-field"><span>归档</span><div class="y13-set-inline">' + (s.project.archived ? ui.status('cancelled', '已归档') : '<span class="y13-muted">未归档</span>') +
      (s.project.archived
        ? (canRestore ? ui.button({ label: '恢复项目', kind: 'small primary', cmd: 'project.restore', data: { project: s.project.id, base_version: s.project.version } }) : '')
        : (canArchive ? ui.button({ label: '归档', kind: 'small danger', cmd: 'project.archive', data: { project: s.project.id, base_version: s.project.version } }) : '')) + '</div></div>';
    const body = '<div class="y13-set-basic">' + nameRow + goalRow + pinRow + archiveRow + '</div>' +
      (s.project.archived ? ui.note('归档只读：查询仍可用，写命令会返回冲突。', 'warn') : '');
    return ui.block({ title: '基本信息', query: 'project.settings', command: Y13.cap.command('project.set_goal') ? 'project.set_goal' : null, body: body });
  }

  function deptCard(ctx, s, department) {
    const entry = s.departments[department];
    const resolved = entry.resolved || {};
    const promptLabel = entry.prompt_text ? '配置 v' + entry.prompt_version : '默认 v0';
    const preview = entry.prompt_text ? entry.prompt_text : '内置默认 Prompt';
    const rows = [
      ['模型', (entry.model ? '' : '<small class="y13-muted y13-block-line">跟随部门默认</small>') +
        (resolved.definition ? '<span class="y13-set-stack"><strong>' + esc(resolved.label) + '</strong><small class="y13-muted">来源：' + esc(resolved.source || '—') + '</small>' +
          (resolved.problem ? ui.status('unusable', '无法使用：' + resolved.problem) : ui.status('admitted', '已准入')) + '</span>' : ui.status('idle', '未设置'))],
      ['推理档位', resolved.definition ? esc((resolved.request_level ? '请求 ' + resolved.request_level : '请求档位为空（模型默认）') + ' · 发送 ' + (resolved.sent_level || '不带推理参数')) : ''],
      ['部门 Prompt', ui.tag(promptLabel) + '<small class="y13-muted y13-block-line y13-set-clip">' + esc(preview) + '</small>'],
      ['设置版本', entry.version ? ui.code('v' + entry.version) : '<span class="y13-muted">尚未写入，全部跟随</span>']
    ];
    return '<article class="y13-set-dept' + (department === 'operations' ? ' is-ops' : '') + '">' +
      '<header><h3>' + esc(LABELS[department]) + '部门</h3>' + (department === 'operations' ? ui.tag('Stage 4') : '') + '</header>' +
      ui.kv(rows, 'is-rows') +
      '<div class="y13-row">' + ui.button({ label: '编辑部门设置', kind: 'small', act: 'dept.openSettings', data: { project: s.project.id, department: department } }) + '</div></article>';
  }

  function deptBlock(ctx, s) {
    const cards = DEPTS.filter((department) => s.departments[department]).map((department) => deptCard(ctx, s, department)).join('');
    return ui.block({
      title: '部门设置', query: 'project.settings', command: 'department_settings.save',
      subtitle: '本项目各部门的项目部门设置，内容同部门设置弹窗；没有写入的项跟随部门默认，不修改部门默认。',
      body: '<div class="y13-set-depts">' + cards + '</div>'
    });
  }

  // 源目录（3.8 起另有采纳写回的三项设置与写回检查的命令，工单 #709、#815）
  function writebackText(dir) {
    const w = dir.writeback;
    if (!w || !w.enabled) return '<span class="y13-muted">没有打开</span>';
    return ui.status('succeeded', '打开') + ' <span>' + esc(w.remote) + ' → ' + esc(w.target_branch) + '</span>';
  }

  function sourceBlock(s) {
    const store = s.source_directories;
    const withWriteback = Y13.cap.command('writeback.execute');
    const columns = [
      { key: 'name', label: '名称', render: (row) => ui.code(row.name) },
      { key: 'path', label: '路径', render: (row) => '<span class="y13-set-url">' + esc(row.path) + '</span>' }
    ];
    if (withWriteback) {
      columns.push(
        { key: 'writeback', label: '采纳写回', render: (row) => writebackText(row) },
        { key: 'checks', label: '写回检查的命令', render: (row) => ((row.check_commands || []).length ? row.check_commands.map((cmd) => ui.code(cmd)).join(' ') : '<span class="y13-muted">没有</span>') }
      );
    }
    const table = store.items.length ? ui.table({ columns, rows: store.items }) : ui.empty('还没有登记源目录');
    const writebackFields = withWriteback
      ? '<label class="y13-field"><span>采纳写回</span><select class="y13-select" id="y13-set-src-wb"><option value="">保持原来的设置</option><option value="on">打开：采纳以后把成果写回这个目录</option><option value="off">关闭</option></select></label>' +
        '<label class="y13-field"><span>远端</span><input class="y13-input y13-set-mono" type="text" id="y13-set-src-remote" placeholder="例如 origin" data-draft="set.src.remote"></label>' +
        '<label class="y13-field"><span>目标分支</span><input class="y13-input y13-set-mono" type="text" id="y13-set-src-branch" placeholder="例如 main" data-draft="set.src.branch"></label>' +
        '<label class="y13-field y13-set-wide"><span>写回检查的命令（每行一条，可选）</span><textarea class="y13-textarea y13-set-mono" rows="2" id="y13-set-src-checks" data-draft="set.src.checks" placeholder="例如 python -m pytest tests"></textarea>' +
        '<small class="y13-muted">写回之前在目标仓库里运行；命令原样执行，不需要登记。不填的项保留原来的设置。</small></label>'
      : '';
    const form = '<div class="y13-set-form"><h3 class="y13-h3">登记源目录 · 基于 v' + esc(store.version) + '</h3>' +
      '<div class="y13-set-form-grid">' +
      '<label class="y13-field"><span>名称</span><input class="y13-input" type="text" id="y13-set-src-name" placeholder="例如 webapp" data-draft="set.src.name"></label>' +
      '<label class="y13-field y13-set-wide"><span>路径</span><input class="y13-input y13-set-mono" type="text" id="y13-set-src-path" placeholder="/work/webapp 或服务所在机器上的绝对路径" data-draft="set.src.path"></label>' +
      writebackFields +
      '</div><div class="y13-row">' + ui.button({ label: '保存源目录', kind: 'primary', act: 'set.saveSource', disabled: s.project.archived }) +
      '<small class="y13-muted">同名登记覆盖原来的设置，版本加一。</small></div></div>';
    return ui.block({
      title: '源目录', query: 'project.settings', command: 'source_directory.save',
      subtitle: '登记在这台控制主机上的代码目录：接入已有项目时建档从这里采集快照' + (withWriteback ? '，采纳的成果写回这里' : '') + '。新事项从项目的起点开始，不再逐个事项选择源目录。',
      body: table + form
    });
  }

  // 成果写回（应用层与接口层设计说明「写回在页面上的显示」）：发起写回、写回记录的五种结果；合并请求还只是本地记录时照实写明
  const WB_KIND = { completed: 'succeeded', verified: 'succeeded', stopped: 'failed', held: 'waiting', not_needed: 'idle' };

  function writebackRow(row) {
    const parts = [];
    if (row.pushed_branch) parts.push('推送分支 ' + row.pushed_branch + ' → 目标分支 ' + row.target_branch);
    if (row.status === 'held') parts.push('等前一次采纳合入目标分支');
    if (row.status === 'not_needed') parts.push('变更已经在目标分支上');
    if (row.stop_reason) parts.push('停止原因：' + (row.stop_reason.text || row.stop_reason));
    if ((row.conflicts || []).length) parts.push('冲突的文件：' + row.conflicts.join('、'));
    return parts.join('；');
  }

  function writebackBlock(s) {
    if (!Y13.cap.query('project.writeback')) return '';
    const data = Y13.api.query('project.writeback', { project: s.project.id }).data;
    const head = data.enabled
      ? '<p>' + ui.status('succeeded', '采纳写回已打开') + ' <span class="y13-muted">写回到源目录 ' + esc(data.source_name) + '，目标分支 ' + esc(data.target_branch) + '</span></p>'
      : ui.note('源目录还没有打开采纳写回：在上面的源目录一节里打开，并写明远端与目标分支。', 'info');
    const table = data.records.length
      ? ui.table({
        columns: [
          { key: 'adoption', label: '采纳成果', render: (row) => ui.code(row.adoption) },
          { key: 'status', label: '结果', render: (row) => ui.status(WB_KIND[row.status] || 'idle', row.status_text) },
          { key: 'at', label: '时间', render: (row) => esc(Y13.ui.time(row.at)) },
          { key: 'detail', label: '说明', render: (row) => esc(writebackRow(row)) || '<span class="y13-muted">—</span>' },
          { key: 'mr', label: '合并请求', render: (row) => (row.merge_request ? esc(row.merge_request.title) + (row.merge_request.local_only ? ' ' + ui.tag('还只是本地记录') : '') : '<span class="y13-muted">没有</span>') }
        ],
        rows: data.records
      })
      : ui.empty('还没有写回记录');
    return ui.block({
      title: '成果写回', query: 'project.writeback', command: 'writeback.execute',
      subtitle: '把采纳的成果写回登记的源目录。结果有五种：写回完成、写回已核实、写回停止、写回等待、无需写回；当前版本只在本地记录合并请求，还没有在代码托管平台上创建。',
      actions: ui.button({ label: '写回成果', icon: 'import', kind: 'small primary', act: 'set.writeback', data: { project: s.project.id }, disabled: s.project.archived }),
      body: head + table
    });
  }

  function machineRow(list, s, machine) {
    const auth = s.machines.find((entry) => entry.machine_id === machine.id);
    return '<div class="y13-set-dept" data-machine-id="' + esc(machine.id) + '"><header><h3>' + esc(machine.name) + '</h3>' +
      '<label class="y13-field is-inline"><input type="checkbox" data-machine-use' + (auth ? ' checked' : '') + '><span>授权使用</span></label></header>' +
      '<p class="y13-muted y13-small">' + esc(machine.address) + ' · ' + esc(machine.purpose || '') + (machine.online ? '' : ' · 离线') + '</p>' +
      '<label class="y13-field"><span>登记的目录（每行一个）</span><textarea class="y13-textarea y13-set-mono" rows="2" data-machine-dirs>' + esc((auth && auth.dirs ? auth.dirs : []).join('\n')) + '</textarea></label>' +
      (Y13.cap.query('ops.status')
        ? '<label class="y13-field is-inline"><input type="checkbox" data-machine-runtime' + (auth && auth.runtime_env ? ' checked' : '') + '><span>作为运行环境</span></label>' +
          '<label class="y13-field"><span>常设授权清单（每行一个）</span><textarea class="y13-textarea y13-set-mono" rows="2" data-machine-standing>' + esc((auth && auth.standing ? auth.standing : []).join('\n')) + '</textarea></label>'
        : '') +
      '</div>';
  }

  function machinesBlock(s) {
    const list = machines();
    if (!list) return ui.empty('系统页的机器查询还没有登记');
    const rows = list.map((machine) => machineRow(list, s, machine)).join('');
    return ui.block({
      title: '机器授权', query: ['project.settings', 'machines.list'], command: 'machine_authorization.save',
      subtitle: '从系统登记的机器中选择本项目可以使用的机器，每台写明登记的目录；命令在登记的目录里原样执行，不逐条授权。Stage 4 起可以指定为本项目的运行环境并批准常设授权清单。当前版本 v' + esc(s.machines_version) + '。',
      body: '<div class="y13-set-depts">' + rows + '</div>' +
        '<div class="y13-row">' + ui.button({ label: '保存机器授权', kind: 'primary', act: 'set.saveMachines', disabled: s.project.archived }) + '</div>'
    });
  }

  function placementOptions(list, current, extraLabel) {
    const options = ['<option value=""' + (current ? '' : ' selected') + '>' + esc(extraLabel) + '</option>',
      '<option value="local_process"' + (current === 'local_process' ? ' selected' : '') + '>' + esc(PLACE_LABELS.local_process) + '</option>'];
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
    const checkRow = (department) => '<label class="y13-field"><span>' + esc(LABELS[department]) + '的检查</span>' +
      '<select class="y13-select" data-place-check="' + department + '">' + placementOptions(list, checks[department] || '', '与运行工作区相同') + '</select></label>';
    return ui.block({
      title: '执行位置', query: ['project.settings', 'machines.list'], command: 'execution_placement.save',
      subtitle: '运行工作区的位置与产品·工程·质检各自检查的位置：本机进程或授权的机器；位置是登记的机器时，它必须在本项目的机器授权中。当前版本 v' + esc(place.version) + '。',
      body: '<div class="y13-set-form-grid">' +
        '<label class="y13-field"><span>运行工作区</span><select class="y13-select" id="y13-set-place-workspace">' + placementOptions(list, place.workspace, '本机进程') + '</select></label>' +
        checkRow('product') + checkRow('engineering') + checkRow('quality') +
        '</div><div class="y13-row">' + ui.button({ label: '保存执行位置', kind: 'primary', act: 'set.savePlacement', disabled: s.project.archived }) + '</div>'
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
        return '<div class="y13-dm-role" data-role-id="' + esc(role.role_id) + '">' +
          '<div class="y13-dm-role-name"><strong>' + esc(role.name || role.role_id) + '</strong><small class="y13-muted">' + esc(role.duty || '') + '</small></div>' +
          '<label class="y13-field"><span>模型</span><select class="y13-select" data-role-model>' + options + '</select></label>' +
          '<label class="y13-field"><span>推理档位</span><select class="y13-select" data-role-level>' + levels + '</select></label>' +
          '<label class="y13-field y13-dm-role-prompt"><span>角色 Prompt</span><textarea class="y13-textarea" rows="2" data-role-prompt placeholder="空为内置默认">' + esc(role.prompt_text || '') + '</textarea></label>' +
          '</div>';
      }).join('');
      return '<section class="y13-set-roles" data-roles-dept="' + esc(department) + '"><div class="y13-set-roles-head"><h3 class="y13-h3">' + esc(LABELS[department]) + '部门</h3>' +
        ui.tag('Stage 5') + '</div><div class="y13-dm-roles">' + rows + '</div>' +
        '<div class="y13-row">' + ui.button({ label: '保存' + esc(LABELS[department]) + '部门的角色设置', kind: 'primary small', act: 'set.saveRoles', data: { department: department }, disabled: s.project.archived }) +
        '<small class="y13-muted">从这些角色下一次模型请求起生效。</small></div></section>';
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
    return '<div class="y13-set">' +
      '<header class="y13-page-head"><div class="y13-page-titles"><p class="y13-eyebrow">项目设置</p><h1>' + esc(s.project.name) + '</h1>' +
      '<p class="y13-subtitle">基本信息、部门设置、源目录与成果写回、机器授权、执行位置与角色设置。</p></div></header>' +
      basicBlock(s) + deptBlock(ctx, s) + sourceBlock(s) + writebackBlock(s) + machinesBlock(s) + placementBlock(s) + opsBlock(s) + rolesBlock(s) +
      '</div>';
  }

  Y13.views.register('settings', {
    title: () => '设置',
    needs: { queries: ['project.settings'] },
    render: render
  });

  Y13.actions.register('set.rename', () => {
    const ctx = Y13.app.ctx();
    const s = settings(ctx);
    const input = document.getElementById('y13-set-name');
    const name = input ? input.value.trim() : '';
    if (!name) {
      Y13.ui.toast('名称不能为空', 'warn');
      return;
    }
    Y13.run('project.rename', { project: ctx.projectId, name: name, base_version: s.project.version });
  });

  Y13.actions.register('set.goal', () => {
    const ctx = Y13.app.ctx();
    const s = settings(ctx);
    const box = document.getElementById('y13-set-goal');
    Y13.run('project.set_goal', { project: ctx.projectId, goal: box ? box.value : '', base_version: s.project.version });
  });

  Y13.actions.register('set.saveSource', () => {
    const ctx = Y13.app.ctx();
    const s = settings(ctx);
    const value = (id) => {
      const el = document.getElementById(id);
      return el ? el.value.trim() : '';
    };
    const params = { project: ctx.projectId, name: value('y13-set-src-name'), path: value('y13-set-src-path'), base_version: s.source_directories.version };
    const wb = document.getElementById('y13-set-src-wb');
    if (wb) {
      if (wb.value) params.writeback_enabled = wb.value === 'on';
      if (value('y13-set-src-remote')) params.remote = value('y13-set-src-remote');
      if (value('y13-set-src-branch')) params.target_branch = value('y13-set-src-branch');
      if (value('y13-set-src-checks')) params.check_commands = lines(value('y13-set-src-checks'));
    }
    const result = Y13.run('source_directory.save', params);
    if (!result.accepted) return;
    ['name', 'path', 'remote', 'branch', 'checks'].forEach((k) => Y13.app.clearDraft('set.src.' + k));
    rerender();
  });

  Y13.actions.register('set.writeback', (el) => {
    Y13.run('writeback.execute', { project: el.dataset.project });
  });

  Y13.actions.register('set.saveMachines', () => {
    const ctx = Y13.app.ctx();
    const s = settings(ctx);
    const rows = Array.prototype.slice.call(document.querySelectorAll('[data-machine-id]'));
    const list = rows.filter((row) => row.querySelector('[data-machine-use]').checked).map((row) => {
      const entry = {
        machine_id: row.dataset.machineId,
        dirs: lines(row.querySelector('[data-machine-dirs]').value)
      };
      if (Y13.cap.query('ops.status')) {
        entry.runtime_env = row.querySelector('[data-machine-runtime]').checked;
        entry.standing = lines(row.querySelector('[data-machine-standing]').value);
      }
      return entry;
    });
    const result = Y13.run('machine_authorization.save', { project: ctx.projectId, machines: list, base_version: s.machines_version });
    if (!result.accepted) return;
    rerender();
  });

  Y13.actions.register('set.savePlacement', () => {
    const ctx = Y13.app.ctx();
    const s = settings(ctx);
    const value = (selector) => {
      const el = document.querySelector(selector);
      return el && el.value ? el.value : null;
    };
    const check = (department) => value('[data-place-check="' + department + '"]');
    const result = Y13.run('execution_placement.save', {
      project: ctx.projectId,
      workspace: value('#y13-set-place-workspace'),
      checks: { product: check('product'), engineering: check('engineering'), quality: check('quality') },
      base_version: s.execution_placement.version
    });
    if (!result.accepted) return;
    rerender();
  });

  Y13.actions.register('set.saveRoles', (el) => {
    const ctx = Y13.app.ctx();
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
    const result = Y13.run('role_settings.save', { project: ctx.projectId, department: department, roles: roles, base_version: s.roles_version });
    if (!result.accepted) return;
    rerender();
  });
})();
