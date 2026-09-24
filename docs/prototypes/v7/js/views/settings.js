// 项目设置（设计说明第 4.6 节）：基本信息、各部门设置、本项目各角色设置（Stage 4）、登记命令（3.2A）、工具授权（3.2B）
(function () {
  'use strict';

  const Y7 = window.Y7;
  const esc = Y7.esc;
  const ui = Y7.ui;

  const DEPTS3 = ['product', 'engineering', 'quality'];
  const APPROVAL_MODES = ['已授权', '超出范围时逐次批准', '每次使用逐次批准'];

  // 页面自己的界面状态：正在编辑的登记命令与工具授权
  const st = { form: null, toolForm: null };

  function rerender() {
    Y7.renderContent(true);
  }

  function rawSettings(projectId) {
    const raw = Y7.data.projectSettings[projectId];
    if (!raw) throw new Error('示例数据缺少项目设置：' + projectId);
    return raw;
  }

  function lines(text) {
    return String(text || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  }

  // ---------------------------------------------------------------------------
  // 查询：基本信息、项目部门设置、项目角色设置（s4）、登记命令（s3）、工具授权与待批准（s3）

  Y7.queries.register('project.settings', (params) => {
    const projectId = params.projectId || Y7.state.projectId;
    const project = Y7.project(projectId);
    if (!project) throw new Error('项目不在当前档位或不存在：' + projectId);
    const raw = rawSettings(projectId);
    const s3 = Y7.atLeast('s3');
    const catalog = s3 ? Y7.resolve(Y7.data.catalog) : null;
    const departments = {};
    Y7.departments().forEach((info) => {
      const written = raw.departments[info.id] || null;
      const entry = written || { model: null, level: null, promptVersion: 0, promptText: null, version: 0 };
      const out = {
        id: info.id, label: info.label, written: Boolean(written),
        promptVersion: entry.promptVersion, promptText: entry.promptText, version: entry.version
      };
      if (s3) {
        out.model = entry.model;
        out.level = entry.level;
        out.effective = Y7.model.resolve(projectId, info.id);
        out.deptDefault = catalog.departmentDefaults[info.id] || null;
      }
      departments[info.id] = out;
    });
    let roles = null;
    if (Y7.atLeast('s4')) {
      roles = {};
      DEPTS3.forEach((dept) => {
        roles[dept] = catalog.roleCatalog[dept].map((role) => {
          const setting = raw.roles && Array.isArray(raw.roles[dept]) ? raw.roles[dept].find((entry) => entry.roleId === role.id) || null : null;
          // resolved 为生效的值；inherited 为跳过本项目角色设置之后继承的值，用于「跟随」一项
          return Object.assign({}, role, {
            setting,
            resolved: Y7.model.resolveRole(projectId, dept, role.id),
            inherited: Y7.model.resolveRole(projectId, dept, role.id, { skipProjectRole: true })
          });
        });
      });
    }
    let commands = null;
    let tools = null;
    let approvals = null;
    let fetches = null;
    if (s3) {
      commands = Y7.clone(raw.commands);
      tools = Y7.clone(raw.tools);
      const registry = Y7.resolve(Y7.data.tools);
      fetches = registry.network.recent.filter((entry) => entry.projectId === projectId).map((entry) => Object.assign({ item: entry.workItemId ? Y7.workItem(entry.workItemId) : null }, entry));
      approvals = fetches.filter((entry) => /等待逐次批准/.test(entry.result));
    }
    return {
      project: { id: project.id, name: project.name, goal: project.goal, pinned: Boolean(project.pinned), archived: Boolean(project.archived) },
      departments, roles, commands, tools, approvals, fetches
    };
  });

  // ---------------------------------------------------------------------------
  // 命令

  // 登记与修改命令（3.2A）：带版本，版本冲突时返回当前配置
  Y7.commands.register('saveCommand', (params) => {
    const projectId = params.projectId;
    const project = Y7.raw.project(projectId);
    if (!project) throw new Error('找不到项目：' + projectId);
    if (project.archived) return { ok: false, message: '归档项目只读：写命令会返回冲突' };
    const list = rawSettings(projectId).commands;
    const name = String(params.name || '').trim();
    if (!/^[a-z][a-z0-9_]*$/.test(name)) return { ok: false, message: '登记名只能包含小写字母、数字与下划线，并以字母开头' };
    const argv = lines(params.argvText);
    if (!argv.length) return { ok: false, message: '固定参数不能为空：至少写入要执行的程序' };
    const args = lines(params.argsText);
    const timeoutSec = Number(params.timeoutSec);
    const outputLimit = Number(params.outputLimit);
    if (!Number.isInteger(timeoutSec) || timeoutSec <= 0) return { ok: false, message: '时限必须是正整数（秒）' };
    if (!Number.isInteger(outputLimit) || outputLimit <= 0) return { ok: false, message: '输出上限必须是正整数（字节）' };
    const existing = list.find((entry) => entry.name === name) || null;
    let version;
    if (params.mode === 'add') {
      if (existing) return { ok: false, message: '登记名「' + name + '」已存在，请修改那一条' };
      version = 1;
      list.push({ name, argv, args, timeoutSec, outputLimit, version });
    } else {
      if (!existing) throw new Error('找不到登记命令：' + name);
      if (Number(params.baseVersion) !== existing.version) {
        return { ok: false, conflict: true, current: Y7.clone(existing), message: '版本冲突：「' + name + '」已更新为 v' + existing.version + '，草稿仍保留，请重新读取后再保存' };
      }
      version = existing.version + 1;
      Object.assign(existing, { argv, args, timeoutSec, outputLimit, version });
    }
    return {
      ok: true,
      message: '已登记命令「' + name + '」v' + version + '：从下一次执行起生效，已开始的执行不受影响',
      paths: ['projectSettings.' + projectId + '.commands']
    };
  });

  // 授权网络与工具（3.2B）：授权范围与批准方式
  Y7.commands.register('authorizeTool', (params) => {
    const projectId = params.projectId;
    const project = Y7.raw.project(projectId);
    if (!project) throw new Error('找不到项目：' + projectId);
    if (project.archived) return { ok: false, message: '归档项目只读：写命令会返回冲突' };
    const tool = rawSettings(projectId).tools.find((entry) => entry.id === params.toolId);
    if (!tool) throw new Error('找不到工具：' + params.toolId);
    const scope = String(params.scope || '').trim();
    if (!scope) return { ok: false, message: '请写明授权范围；不授权时写「未授权」' };
    if (!APPROVAL_MODES.includes(params.approval)) throw new Error('批准方式无效：' + params.approval);
    if (scope === tool.scope && params.approval === tool.approval) return { ok: false, message: '没有需要保存的修改' };
    tool.scope = scope;
    tool.approval = params.approval;
    return { ok: true, message: '已更新「' + tool.label + '」在本项目的授权：' + scope + ' · ' + params.approval, paths: ['projectSettings.' + projectId + '.tools'] };
  });

  // 逐次批准（3.2B）：只批准这一次，不作为永久授权
  Y7.commands.register('approveOnce', (params) => {
    const entry = Y7.data.tools.network.recent.find((item) => item.projectId === params.projectId && item.url === params.url && item.at === params.at);
    if (!entry) throw new Error('找不到等待批准的取回：' + params.url);
    if (!/等待逐次批准/.test(entry.result)) return { ok: false, message: '这次取回已经处理过' };
    if (!['approve', 'reject'].includes(params.decision)) throw new Error('批准决定无效：' + params.decision);
    entry.result = params.decision === 'approve' ? '已批准一次 · 已取回' : '已拒绝 · 没有取回';
    return {
      ok: true,
      message: params.decision === 'approve' ? '已批准这一次取回；批准一次不作为永久授权' : '已拒绝这次取回',
      paths: ['tools.network.recent']
    };
  });

  // 保存角色设置（Stage 4）：本项目某部门各角色的模型、推理档位与角色 Prompt，只写入覆盖的项
  Y7.commands.register('saveRoleSettings', (params) => {
    const projectId = params.projectId;
    const dept = params.department;
    const project = Y7.raw.project(projectId);
    if (!project) throw new Error('找不到项目：' + projectId);
    if (project.archived) return { ok: false, message: '归档项目只读：写命令会返回冲突' };
    if (!DEPTS3.includes(dept)) throw new Error('这个部门没有角色：' + dept);
    const roleCatalog = Y7.data.catalog.roleCatalog[dept];
    const raw = rawSettings(projectId);
    const before = JSON.stringify(Array.isArray(raw.roles[dept]) ? raw.roles[dept] : []);
    const next = [];
    for (const entry of params.entries || []) {
      if (!roleCatalog.some((role) => role.id === entry.roleId)) throw new Error('部门没有这个角色：' + entry.roleId);
      if (entry.model && !(Y7.model.definition(entry.model) && Y7.model.definition(entry.model).admission)) {
        return { ok: false, message: '只能选择已准入的模型访问定义' };
      }
      if (entry.model || entry.level || entry.promptText) {
        next.push({ roleId: entry.roleId, model: entry.model || null, level: entry.level || null, promptText: entry.promptText || null });
      }
    }
    if (JSON.stringify(next) === before) return { ok: false, message: '没有需要保存的修改' };
    raw.roles[dept] = next;
    const paths = ['projectSettings.' + projectId + '.roles.' + dept].concat(Y7.model.afterChange());
    return { ok: true, message: '已保存本项目' + Y7.deptLabel(dept) + '部门的角色设置：从这些角色下一次模型请求起生效', paths };
  });

  // ---------------------------------------------------------------------------
  // 渲染

  function basicBlock(s) {
    const p = s.project;
    const body = '<div class="y7-set-basic">' +
      '<label class="y7-field"><span>名称</span><div class="y7-set-inline"><input class="y7-input" type="text" id="y7-set-name" value="' + esc(p.name) + '"' + (p.archived ? ' readonly' : '') + '>' +
        ui.button({ label: '重命名', act: 'set.rename', disabled: p.archived }) + '</div></label>' +
      '<div class="y7-field"><span>长期目标</span><p class="y7-set-goal">' + esc(p.goal || '尚未填写') + '</p></div>' +
      '<div class="y7-field"><span>置顶</span><div class="y7-set-inline">' + (p.pinned ? ui.status('done', '已置顶') : '<span class="y7-muted">未置顶</span>') +
        ui.button({ label: p.pinned ? '取消置顶' : '置顶', kind: 'small', cmd: 'pinProject', data: { projectId: p.id } }) + '</div></div>' +
      '<div class="y7-field"><span>归档</span><div class="y7-set-inline">' + (p.archived ? ui.status('cancelled', '已归档') : '<span class="y7-muted">未归档</span>') +
        (p.archived
          ? ui.button({ label: '恢复项目', kind: 'small primary', cmd: 'restoreProject', data: { projectId: p.id } })
          : ui.button({ label: '归档', kind: 'small danger', cmd: 'archiveProject', data: { projectId: p.id } })) + '</div></div>' +
      '</div>' + (p.archived ? ui.note('归档只读：查询仍可用，写命令会返回冲突。', 'warn') : '');
    return ui.block({ title: '基本信息', tag: '当前', level: 'now', query: 'project.settings', command: ['renameProject', 'pinProject', 'archiveProject', 'restoreProject'], body });
  }

  // 角色「跟随」时继承的模型与推理档位（跳过本项目角色设置）
  function followText(inherited) {
    const model = inherited.definition ? Y7.model.label(inherited.definition) + ' · ' + inherited.source : '未设置';
    const level = inherited.requestLevel ? inherited.requestLevel + ' · ' + inherited.levelSource : '模型默认档位';
    return '跟随（当前：' + model + '）；档位跟随（当前：' + level + '）';
  }

  function effectiveHtml(e) {
    if (!e.definition) return ui.status('idle', '未设置');
    return '<span class="y7-set-stack"><strong>' + esc(Y7.model.label(e.definition)) + '</strong><small class="y7-muted">来源：' + esc(e.source) + '</small>' +
      (e.problem ? ui.status('unusable', '无法使用：' + e.problem) : ui.status('admitted', '已准入')) + '</span>';
  }

  function deptCard(s, entry) {
    const s3 = Y7.atLeast('s3');
    const promptLabel = entry.promptText === null ? '默认 v0' : '配置 v' + entry.promptVersion;
    const preview = entry.promptText === null ? '内置默认 Prompt' : entry.promptText.split(/\r?\n/)[0];
    const rows = [];
    if (s3) {
      const e = entry.effective;
      rows.push(['模型', (entry.model ? '' : '<small class="y7-muted y7-block-line">跟随部门默认</small>') + effectiveHtml(e)]);
      rows.push(['推理档位', e.definition
        ? esc((e.requestLevel ? '请求 ' + e.requestLevel : '请求档位为空（模型默认）') + ' · 发送 ' + (e.sentLevel || '不带推理参数')) +
          '<small class="y7-muted y7-block-line">档位来源：' + esc(e.levelSource || '模型默认档位') + '</small>'
        : '']);
    }
    rows.push(['部门 Prompt', ui.tag(promptLabel) + '<small class="y7-muted y7-block-line y7-set-clip">' + esc(preview) + '</small>']);
    if (s3) rows.push(['设置版本', entry.written ? ui.code('v' + entry.version) : '<span class="y7-muted">尚未写入，全部跟随</span>']);
    return '<article class="y7-set-dept' + (entry.id === 'operations' ? ' is-ops' : '') + '">' +
      '<header><h3>' + esc(entry.label) + '部门</h3>' + (entry.id === 'operations' ? ui.tag('Stage 5') : '') + '</header>' +
      ui.kv(rows, 'is-rows') +
      '<div class="y7-row">' + ui.button({ label: s3 ? '编辑部门设置' : '配置 Prompt', kind: 'small', act: 'dept.openSettings', data: { projectId: s.project.id, department: entry.id } }) + '</div></article>';
  }

  function deptBlock(s) {
    const cards = Object.keys(s.departments).map((dept) => deptCard(s, s.departments[dept])).join('');
    return ui.block({
      title: '部门设置', tag: Y7.atLeast('s3') ? 'D24' : '当前', level: 'now', query: 'project.settings', command: 'saveDepartmentSettings',
      subtitle: Y7.atLeast('s3')
        ? '本项目各部门的项目部门设置，内容同部门设置弹窗；只写入覆盖的项，没有写入的项跟随部门默认，不修改部门默认。修改从该部门下一次模型请求起生效，包括进行中的事项。'
        : '本项目各部门的部门 Prompt；模型在「模型与 Provider」页的三部门绑定中设置，在途事项沿用创建时的快照。',
      body: '<div class="y7-set-depts">' + cards + '</div>'
    });
  }

  function rolesBlock(s) {
    if (!s.roles) return '';
    const sections = DEPTS3.map((dept) => {
      const table = ui.table({
        columns: [
          { key: 'name', label: '角色', render: (row) => '<div class="y7-cell-stack"><strong>' + esc(row.name) + '</strong><small class="y7-muted">' + esc(row.duty) + '</small></div>' },
          { key: 'model', label: '模型', render: (row) => effectiveHtml(row.resolved) },
          { key: 'level', label: '推理档位', render: (row) => row.resolved.definition ? '<div class="y7-cell-stack"><span>' + esc((row.resolved.requestLevel ? '请求 ' + row.resolved.requestLevel : '请求档位为空') + ' · 发送 ' + (row.resolved.sentLevel || '不带推理参数')) + '</span><small class="y7-muted">来源：' + esc(row.resolved.levelSource || '模型默认档位') + '</small></div>' : '' },
          { key: 'prompt', label: '角色 Prompt', render: (row) => row.resolved.promptText ? '<span class="y7-set-clip">' + esc(row.resolved.promptText) + '</span>' : '<span class="y7-muted">' + esc(row.resolved.promptSource) + '</span>' },
          { key: 'own', label: '本项目写入', render: (row) => '<div class="y7-cell-stack">' + (row.setting ? ui.status('done', '已写入') : '') +
            '<small class="y7-muted">' + esc(followText(row.inherited)) + '</small></div>' }
        ],
        rows: s.roles[dept]
      });
      return '<section class="y7-set-roles"><div class="y7-set-roles-head"><h3 class="y7-h3">' + esc(Y7.deptLabel(dept)) + '部门</h3>' +
        ui.button({ label: '编辑角色设置', kind: 'small', act: 'dept.openSettings', data: { projectId: s.project.id, department: dept } }) + '</div>' + table + '</section>';
    }).join('');
    return ui.block({
      title: '本项目各角色设置', tag: 'Stage 4', level: 's4', query: 'project.settings', command: 'saveRoleSettings',
      subtitle: '解析顺序：项目角色设置、角色默认、项目部门设置、部门默认，取第一个写入了的。角色设置在部门设置弹窗中修改。',
      body: sections
    });
  }

  function commandForm(s) {
    const f = st.form;
    const current = f.mode === 'edit' ? s.commands.find((entry) => entry.name === f.name) : null;
    if (f.mode === 'edit' && !current) throw new Error('找不到登记命令：' + f.name);
    const key = 'set.cmd.' + s.project.id + '.' + (f.mode === 'edit' ? f.name : 'new') + '.';
    const base = current || { name: '', argv: [], args: [], timeoutSec: 60, outputLimit: 16384 };
    const conflict = f.conflict
      ? ui.note('「' + esc(f.name) + '」已被更新为 v' + esc(f.conflict.version) + '（你的修改基于 v' + esc(f.baseVersion) + '）。最新内容：固定参数 ' + ui.code(f.conflict.argv.join(' ')) +
        '，额外参数 ' + ui.code(f.conflict.args.join(' ') || '无') + '，时限 ' + esc(f.conflict.timeoutSec) + ' 秒，输出上限 ' + esc(f.conflict.outputLimit) + ' 字节。你的草稿仍保留在表单中。' +
        '<span class="y7-note-actions">' + ui.button({ label: '重新读取', kind: 'small primary', act: 'set.reloadCommand' }) + '</span>', 'warn')
      : '';
    return '<div class="y7-set-form" id="y7-set-cmd-form"><h3 class="y7-h3">' + (f.mode === 'edit' ? '修改登记命令「' + esc(f.name) + '」 · 基于 v' + esc(f.baseVersion) : '新增登记命令') + '</h3>' + conflict +
      '<div class="y7-set-form-grid">' +
        '<label class="y7-field"><span>登记名</span><input class="y7-input" type="text" id="y7-set-cmd-name" value="' + esc(base.name) + '"' + (f.mode === 'edit' ? ' readonly' : ' data-draft="' + esc(key + 'name') + '"') + ' placeholder="例如 unit_tests"><small class="y7-muted">小写字母、数字与下划线</small></label>' +
        '<label class="y7-field"><span>时限（秒）</span><input class="y7-input" type="number" min="1" id="y7-set-cmd-timeout" value="' + esc(base.timeoutSec) + '" data-draft="' + esc(key + 'timeout') + '"></label>' +
        '<label class="y7-field"><span>输出上限（字节）</span><input class="y7-input" type="number" min="1" id="y7-set-cmd-limit" value="' + esc(base.outputLimit) + '" data-draft="' + esc(key + 'limit') + '"></label>' +
        '<label class="y7-field y7-set-wide"><span>固定参数（每行一个）</span><textarea class="y7-textarea y7-set-mono" rows="4" id="y7-set-cmd-argv" data-draft="' + esc(key + 'argv') + '">' + esc(base.argv.join('\n')) + '</textarea></label>' +
        '<label class="y7-field y7-set-wide"><span>允许的额外参数（每行一个）</span><textarea class="y7-textarea y7-set-mono" rows="3" id="y7-set-cmd-args" data-draft="' + esc(key + 'args') + '">' + esc(base.args.join('\n')) + '</textarea><small class="y7-muted">模型只能在这些参数中选择；私有路径与越界参数会被拒绝。</small></label>' +
      '</div>' +
      '<div class="y7-row">' + ui.button({ label: '保存', kind: 'primary', act: 'set.saveCommand' }) + ui.button({ label: '取消', act: 'set.cancelCommand' }) + '</div>' +
      (f.mode === 'edit' ? '<p class="y7-proto-helper">原型演示：<button type="button" class="y7-link" data-act="set.simulateCommandConflict">模拟另一处先修改了这条命令</button>，用来查看版本冲突的提示。</p>' : '') +
      '</div>';
  }

  function commandsBlock(s) {
    if (!s.commands) return '';
    const table = ui.table({
      columns: [
        { key: 'name', label: '登记名', render: (row) => ui.code(row.name) },
        { key: 'argv', label: '固定参数', render: (row) => ui.code(row.argv.join(' ')) },
        { key: 'args', label: '允许的额外参数', render: (row) => row.args.length ? row.args.map((arg) => ui.code(arg)).join(' ') : '<span class="y7-muted">不允许</span>' },
        { key: 'timeoutSec', label: '时限', render: (row) => esc(row.timeoutSec + ' 秒') },
        { key: 'outputLimit', label: '输出上限', render: (row) => esc(Y7.ui.num(row.outputLimit) + ' 字节') },
        { key: 'version', label: '版本', render: (row) => ui.code('v' + row.version) },
        { key: 'ops', label: '操作', className: 'y7-col-actions', render: (row) => ui.button({ label: '修改', kind: 'small', act: 'set.editCommand', data: { name: row.name }, disabled: s.project.archived }) }
      ],
      rows: s.commands,
      empty: '本项目还没有登记命令'
    });
    return ui.block({
      title: '登记命令', tag: '3.2A', level: 's3', query: 'project.settings', command: 'saveCommand',
      subtitle: '部门只能执行这里登记的命令：固定参数不可改，额外参数只能从允许的列表中选；超时、输出过量与越界参数都有可核实的状态。',
      actions: st.form ? '' : ui.button({ label: '新增登记命令', icon: 'plus', kind: 'small', act: 'set.addCommand', disabled: s.project.archived }),
      body: table + (st.form && st.form.projectId === s.project.id ? commandForm(s) : '')
    });
  }

  function toolForm(s) {
    const f = st.toolForm;
    const tool = s.tools.find((entry) => entry.id === f.toolId);
    if (!tool) throw new Error('找不到工具：' + f.toolId);
    const key = 'set.tool.' + s.project.id + '.' + tool.id + '.';
    return '<div class="y7-set-form"><h3 class="y7-h3">修改「' + esc(tool.label) + '」的授权</h3><div class="y7-set-form-grid">' +
      '<label class="y7-field y7-set-wide"><span>授权范围</span><input class="y7-input" type="text" id="y7-set-tool-scope" value="' + esc(tool.scope) + '" data-draft="' + esc(key + 'scope') + '"><small class="y7-muted">例如允许取回的域名；不授权时写「未授权」</small></label>' +
      '<label class="y7-field"><span>批准方式</span><select class="y7-select" id="y7-set-tool-approval">' + APPROVAL_MODES.map((mode) => '<option' + (mode === tool.approval ? ' selected' : '') + '>' + esc(mode) + '</option>').join('') + '</select></label>' +
      '</div><div class="y7-row">' + ui.button({ label: '保存授权', kind: 'primary', act: 'set.saveTool' }) + ui.button({ label: '取消', act: 'set.cancelTool' }) + '</div></div>';
  }

  function toolsBlock(s) {
    if (!s.tools) return '';
    const table = ui.table({
      columns: [
        { key: 'label', label: '工具' },
        { key: 'scope', label: '授权范围', render: (row) => /未授权/.test(row.scope) ? ui.status('idle', row.scope) : esc(row.scope) },
        { key: 'approval', label: '批准方式' },
        { key: 'ops', label: '操作', className: 'y7-col-actions', render: (row) => ui.button({ label: '修改授权', kind: 'small', act: 'set.editTool', data: { toolId: row.id }, disabled: s.project.archived }) }
      ],
      rows: s.tools,
      empty: '本项目还没有网络或 MCP 工具的授权'
    });
    const approvals = s.approvals.length
      ? '<ul class="y7-set-approvals">' + s.approvals.map((entry) =>
        '<li><div class="y7-set-stack"><strong class="y7-set-url">' + esc(entry.url) + '</strong><small class="y7-muted">' + esc(Y7.ui.time(entry.at)) + (entry.item ? ' · 事项「' + esc(entry.item.title) + '」' : '') + ' · 超出授权范围</small></div>' +
        '<div class="y7-row">' + ui.button({ label: '批准一次', kind: 'small primary', cmd: 'approveOnce', data: { projectId: s.project.id, url: entry.url, at: entry.at, decision: 'approve' } }) +
        ui.button({ label: '拒绝', kind: 'small danger', cmd: 'approveOnce', data: { projectId: s.project.id, url: entry.url, at: entry.at, decision: 'reject' } }) + '</div></li>'
      ).join('') + '</ul>'
      : ui.empty('没有等待逐次批准的请求');
    const fetches = s.fetches.length
      ? ui.table({
        columns: [
          { key: 'at', label: '时间', render: (row) => esc(Y7.ui.time(row.at)) },
          { key: 'url', label: '地址', render: (row) => '<span class="y7-set-url">' + esc(row.url) + '</span>' },
          { key: 'item', label: '事项', render: (row) => row.item ? esc(row.item.title) : '' },
          { key: 'result', label: '结果' }
        ],
        rows: s.fetches
      })
      : ui.empty('本项目还没有网络取回');
    return ui.block({
      title: '工具授权', tag: '3.2B · 设计待定', level: 's3', query: 'project.settings', command: ['authorizeTool', 'approveOnce'],
      subtitle: '网络取回与各 MCP 工具在本项目的授权范围；超出授权时逐次批准，批准一次不作为永久授权。',
      body: table + (st.toolForm && st.toolForm.projectId === s.project.id ? toolForm(s) : '') +
        '<h3 class="y7-h3">等待逐次批准</h3>' + approvals +
        '<h3 class="y7-h3">本项目最近的网络取回</h3>' + fetches
    });
  }

  Y7.views.register('settings', {
    title: () => '设置',
    render(ctx) {
      const s = Y7.query('project.settings', { projectId: ctx.project.id });
      if (st.form && st.form.projectId !== s.project.id) st.form = null;
      if (st.toolForm && st.toolForm.projectId !== s.project.id) st.toolForm = null;
      return '<div class="y7-set">' +
        '<header class="y7-page-head"><div class="y7-page-titles"><p class="y7-eyebrow">项目设置</p><h1>' + esc(s.project.name) + '</h1>' +
        '<p class="y7-subtitle">基本信息、各部门设置' + (Y7.atLeast('s3') ? '、登记命令与工具授权' : '') + '。</p></div></header>' +
        basicBlock(s) + deptBlock(s) + rolesBlock(s) + commandsBlock(s) + toolsBlock(s) +
        '</div>';
    }
  });

  // ---------------------------------------------------------------------------
  // 界面动作

  function clearCommandDrafts(projectId, name) {
    const key = 'set.cmd.' + projectId + '.' + (name || 'new') + '.';
    ['name', 'timeout', 'limit', 'argv', 'args'].forEach((field) => Y7.clearDraft(key + field));
  }

  Y7.actions.register('set.rename', () => {
    Y7.command('renameProject', { projectId: Y7.state.projectId, name: document.getElementById('y7-set-name').value });
  });

  Y7.actions.register('set.addCommand', () => {
    st.form = { projectId: Y7.state.projectId, mode: 'add', name: null, baseVersion: null, conflict: null };
    rerender();
  });

  Y7.actions.register('set.editCommand', (el) => {
    const s = Y7.query('project.settings', { projectId: Y7.state.projectId });
    const cmd = s.commands.find((entry) => entry.name === el.dataset.name);
    if (!cmd) throw new Error('找不到登记命令：' + el.dataset.name);
    st.form = { projectId: Y7.state.projectId, mode: 'edit', name: cmd.name, baseVersion: cmd.version, conflict: null };
    rerender();
  });

  Y7.actions.register('set.cancelCommand', () => {
    clearCommandDrafts(st.form.projectId, st.form.mode === 'edit' ? st.form.name : null);
    st.form = null;
    rerender();
  });

  Y7.actions.register('set.saveCommand', () => {
    const f = st.form;
    const result = Y7.command('saveCommand', {
      projectId: f.projectId,
      mode: f.mode,
      name: document.getElementById('y7-set-cmd-name').value,
      argvText: document.getElementById('y7-set-cmd-argv').value,
      argsText: document.getElementById('y7-set-cmd-args').value,
      timeoutSec: document.getElementById('y7-set-cmd-timeout').value,
      outputLimit: document.getElementById('y7-set-cmd-limit').value,
      baseVersion: f.baseVersion
    });
    if (result.ok) {
      clearCommandDrafts(f.projectId, f.mode === 'edit' ? f.name : null);
      st.form = null;
      rerender();
      return;
    }
    if (result.conflict) {
      f.conflict = result.current;
      rerender();
    }
  });

  Y7.actions.register('set.reloadCommand', () => {
    const f = st.form;
    f.baseVersion = f.conflict.version;
    f.conflict = null;
    rerender();
    Y7.ui.toast('已重新读取 v' + f.baseVersion + '；草稿保留，检查后再保存');
  });

  // 原型演示：另一处先修改了这条命令，下一次保存会遇到版本冲突
  Y7.actions.register('set.simulateCommandConflict', () => {
    const cmd = rawSettings(st.form.projectId).commands.find((entry) => entry.name === st.form.name);
    if (!cmd) throw new Error('找不到登记命令：' + st.form.name);
    cmd.version += 1;
    cmd.timeoutSec += 30;
    Y7.ui.toast('原型：「' + cmd.name + '」已在另一处保存为 v' + cmd.version);
  });

  Y7.actions.register('set.editTool', (el) => {
    st.toolForm = { projectId: Y7.state.projectId, toolId: el.dataset.toolId };
    rerender();
  });

  Y7.actions.register('set.cancelTool', () => {
    Y7.clearDraft('set.tool.' + st.toolForm.projectId + '.' + st.toolForm.toolId + '.scope');
    st.toolForm = null;
    rerender();
  });

  Y7.actions.register('set.saveTool', () => {
    const f = st.toolForm;
    const result = Y7.command('authorizeTool', {
      projectId: f.projectId,
      toolId: f.toolId,
      scope: document.getElementById('y7-set-tool-scope').value,
      approval: document.getElementById('y7-set-tool-approval').value
    });
    if (!result.ok) return;
    Y7.clearDraft('set.tool.' + f.projectId + '.' + f.toolId + '.scope');
    st.toolForm = null;
    rerender();
  });
})();
