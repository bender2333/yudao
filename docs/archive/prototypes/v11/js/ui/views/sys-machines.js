// 机器系统页（设计说明第 9.2 节、3.2C）：上方机房放大画面，下方机器列表与登记表单
(function () {
  'use strict';
  const Y11 = window.Y11;
  const DEPT_LABELS = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const KIND_LABELS = { host: '控制主机', desktop: '台式机', pi: '树莓派', laptop: '笔记本' };

  let panel = null;
  let editing = null;

  function redraw() { Y11.app.renderContent(true); }
  function machines() { return Y11.api.query('machines.list').data; }

  function refreshSection(root, selector, html) {
    const el = root.querySelector(selector);
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const next = tmp.firstElementChild;
    if (el && next) el.replaceWith(next);
    else if (el && !next) el.remove();
  }

  function actionsCell(machine) {
    if (!machine.actions.length) return '<span class="y11-muted">没有动作</span>';
    return '<div class="y11-cell-stack">' + machine.actions.map((action) =>
      Y11.ui.status(action.state === 'unknown' ? 'unknown' : 'running', action.state === 'unknown' ? '结果未知' : '执行中') +
      '<span>' + Y11.esc(action.project_name) + ' · ' + Y11.esc(DEPT_LABELS[action.department] || action.department) + ' · ' + Y11.esc(action.label) + '</span>').join('') + '</div>';
  }

  function listBlock() {
    const rows = machines().map((machine) => ({
      machine,
      name: '<div class="y11-cell-stack"><strong>' + Y11.esc(machine.name) + '</strong><small class="y11-muted">' + Y11.esc(KIND_LABELS[machine.kind] || machine.kind) + '</small></div>',
      address: Y11.ui.code(machine.address),
      purpose: Y11.esc(machine.purpose),
      online: '<div class="y11-cell-stack">' + (machine.online ? Y11.ui.status('running', '在线') : Y11.ui.status('offline', '离线')) +
        '<small class="y11-muted">最近心跳 ' + Y11.esc(Y11.ui.time(machine.last_heartbeat_at)) + '</small></div>',
      actions: actionsCell(machine),
      authorized: machine.authorized_projects.length ? machine.authorized_projects.map((p) => Y11.esc(p.name)).join('、') : '<span class="y11-muted">没有授权的项目</span>',
      runtime_for: machine.runtime_for === undefined
        ? null
        : (machine.runtime_for.length
          ? machine.runtime_for.map((entry) => Y11.esc(entry.name) + ' · ' + Y11.esc(entry.version) + (machine.fault ? Y11.ui.status('failed', '故障') : '')).join('、')
          : '<span class="y11-muted">没有运行环境</span>'),
      act: Y11.ui.button({ label: '修改', kind: 'small', act: 'machines.edit', data: { machineId: machine.id } })
    }));
    const columns = [
      { key: 'name', label: '名称', render: (row) => row.name },
      { key: 'address', label: '地址', render: (row) => row.address },
      { key: 'purpose', label: '用途', render: (row) => row.purpose },
      { key: 'online', label: '状态', render: (row) => row.online },
      { key: 'actions', label: '正在执行的动作', render: (row) => row.actions },
      { key: 'authorized', label: '授权使用它的项目', render: (row) => row.authorized }
    ];
    if (rows.length && rows[0].runtime_for !== null) columns.push({ key: 'runtime_for', label: '运行环境', render: (row) => row.runtime_for });
    columns.push({ key: 'act', label: '操作', className: 'y11-col-actions', render: (row) => row.act });
    return Y11.ui.block({
      id: 'sys-machine-list',
      title: '机器', query: 'machines.list', command: 'machine.save',
      subtitle: '登记以后由执行代理报到；心跳超时的机器上，动作结果未知',
      actions: Y11.ui.button({ label: '登记机器', kind: 'small primary', act: 'machines.new' }),
      body: Y11.ui.table({ columns, rows })
    });
  }

  function formBlock() {
    if (!editing) return '';
    const machine = editing === 'new' ? null : machines().find((item) => item.id === editing);
    if (editing !== 'new' && !machine) return '';
    const body = '<div class="y11-form">' +
      '<label class="y11-field"><span>名称</span><input class="y11-input" type="text" id="y11-machine-name" value="' + Y11.esc(machine ? machine.name : '') + '"></label>' +
      '<label class="y11-field"><span>地址</span><input class="y11-input" type="text" id="y11-machine-address" value="' + Y11.esc(machine ? machine.address : '') + '"></label>' +
      '<label class="y11-field"><span>用途</span><input class="y11-input" type="text" id="y11-machine-purpose" value="' + Y11.esc(machine ? machine.purpose : '') + '"></label>' +
      '<fieldset class="y11-field"><legend>认证</legend><input class="y11-input" type="text" value="尚未设计" disabled><small class="y11-muted">TODO：执行代理的认证方式尚未设计，灰色显示。</small></fieldset>' +
      '<div class="y11-row">' +
        Y11.ui.button({ label: machine ? '保存' : '登记', kind: 'primary', act: 'machines.save' }) +
        Y11.ui.button({ label: '取消', act: 'machines.cancel' }) +
      '</div></div>';
    return Y11.ui.block({
      id: 'sys-machine-form',
      title: machine ? '修改机器「' + machine.name + '」' : '登记机器',
      className: 'y11-form-block', query: 'machines.list', command: 'machine.save', body
    });
  }

  function render() {
    return '<div class="y11-sys-machines">' +
      Y11.ui.block({
        title: '机房', query: 'machines.list',
        subtitle: '与首页地下室相同的放大画面；点击设备打开修改表单',
        body: '<div id="sys-machine-room"></div>'
      }) +
      listBlock() +
      formBlock() +
      '</div>';
  }

  function mount(ctx, root) {
    const host = root.querySelector('#sys-machine-room');
    panel = Y11.scenes.mountMachineRoom(host, {
      onMachineClick(id) { editing = id; redraw(); }
    });
  }

  function update(ctx, root) {
    refreshSection(root, '#sys-machine-list', listBlock());
    refreshSection(root, '#sys-machine-form', formBlock());
    if (panel) panel.update();
  }

  Y11.views.register('sys-machines', {
    title: () => '机器',
    needs: { queries: ['machines.list'], commands: ['machine.save'] },
    render, mount, update,
    onEvent: (ctx, root, ev) => { if (panel) panel.onEvent(ev); },
    unmount: () => { if (panel) panel.destroy(); panel = null; }
  });

  Y11.actions.register('machines.new', () => { editing = 'new'; redraw(); });

  Y11.actions.register('machines.edit', (el) => { editing = el.dataset.machineId; redraw(); });

  Y11.actions.register('machines.cancel', () => { editing = null; redraw(); });

  Y11.actions.register('machines.save', () => {
    const name = document.getElementById('y11-machine-name').value.trim();
    const address = document.getElementById('y11-machine-address').value.trim();
    const purpose = document.getElementById('y11-machine-purpose').value.trim();
    const machine = editing === 'new' ? null : machines().find((item) => item.id === editing);
    const params = { name, address, purpose };
    if (machine) {
      params.machine_id = machine.id;
      params.base_version = machine.version;
    }
    const result = Y11.run('machine.save', params);
    if (!result.accepted) return;
    editing = null;
    redraw();
  });
})();
