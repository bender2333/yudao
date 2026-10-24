// 运行与执行槽位页（设计说明第 9.3 节）：槽位、跨项目队列、排空与数据保留
(function () {
  'use strict';
  const Y13 = window.Y13;
  const DEPT_LABELS = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };
  const DRAIN_LABELS = { none: '未排空', draining: '排空中', forced: '已强制升级' };

  function slots() { return Y13.cap.query('runtime.slots') ? Y13.api.query('runtime.slots').data : null; }
  function status() { return Y13.api.query('system.status').data; }

  function redraw() { Y13.app.renderContent(true); }

  function slotBlock(data) {
    const lamps = Array.from({ length: data.total }, (_, index) =>
      '<span class="y13-lamp' + (index < data.used.length ? ' is-on' : '') + '" title="' + (index < data.used.length ? '已占用' : '空闲') + '"></span>').join('');
    const options = [1, 2, 3, 4, 5, 6, 7, 8].map((n) =>
      '<option value="' + n + '"' + (n === data.total ? ' selected' : '') + '>' + n + '</option>').join('');
    const used = Y13.ui.table({
      columns: [
        { key: 'title', label: '正在执行的事项', render: (row) => '<div class="y13-cell-stack"><strong>' + Y13.esc(row.title) + '</strong><small class="y13-muted">' + Y13.esc(row.project_name || row.project_id) + '</small></div>' },
        { key: 'department', label: '部门', render: (row) => Y13.esc(row.department_label || DEPT_LABELS[row.department] || row.department) + (data.unit === 'role' && row.role ? ' · ' + Y13.esc(row.role_label || row.role) : '') },
        { key: 'elapsed', label: '已用时间 / 上限', render: (row) => Y13.esc(Y13.ui.duration(row.elapsed_sec)) + ' / ' + Y13.esc(Y13.ui.duration(row.limit_sec)) }
      ],
      rows: data.used,
      empty: '没有正在执行的事项'
    });
    const queue = Y13.ui.table({
      columns: [
        { key: 'position', label: '位置', render: (row) => '<span class="y13-ticket">' + row.position + '</span>' },
        { key: 'title', label: '等待中的事项', render: (row) => '<div class="y13-cell-stack"><strong>' + Y13.esc(row.title) + '</strong><small class="y13-muted">' + Y13.esc(row.project_name || row.project_id) + '</small></div>' },
        { key: 'since', label: '等待', render: (row) => Y13.esc(Y13.ui.time(row.since)) + '<small class="y13-muted y13-block-line">已等待 ' + Y13.esc(Y13.ui.duration(row.wait_sec)) + '</small>' },
        {
          key: 'reason', label: '排队原因', render: (row) => {
            const tags = [];
            if (row.upgrade_restart) tags.push(Y13.ui.tag('因升级重新开始'));
            if (row.queue_reason === 'slot') tags.push(Y13.ui.tag('等待执行槽位'));
            if (row.queue_reason === 'project') tags.push(Y13.ui.tag('同一项目排队'));
            if (row.queue_reason === 'decision') tags.push(Y13.ui.tag('被决定请求挡住'));
            return tags.join('') || '<span class="y13-muted">—</span>';
          }
        },
        {
          key: 'act', label: '操作', className: 'y13-col-actions', render: (row) =>
            Y13.ui.button({ label: '取消排队', kind: 'small danger', act: 'runtime.cancelQueue', data: { workItemId: row.work_item_id } })
        }
      ],
      rows: data.queue,
      empty: '队列为空'
    });
    return Y13.ui.block({
      title: '执行槽位', query: 'runtime.slots', command: ['runtime.set_slots', 'queue.cancel'],
      subtitle: '执行槽位数是部署设置；三个部门共用一个池子，不同项目并行时按队列顺序取得槽位',
      body: '<div class="y13-slot-row">' +
        '<div class="y13-lamps">' + lamps + '</div>' +
        '<div class="y13-slot-count"><strong>' + data.used.length + ' / ' + data.total + '</strong><span class="y13-muted">已占用 / 总数</span></div>' +
        '<div class="y13-row"><select class="y13-select" id="y13-slot-total">' + options + '</select>' +
        Y13.ui.button({ label: '设置槽位数', kind: 'small', act: 'runtime.setSlots', data: { baseVersion: data.version } }) + '</div>' +
        '</div>' +
        '<h3 class="y13-h3">正在执行的事项</h3>' + used +
        '<h3 class="y13-h3">等待执行槽位的项目</h3>' + queue +
        Y13.ui.note('重启后的队列：' + Y13.esc(data.restart.note) + '（启动于 ' + Y13.esc(Y13.ui.time(data.restart.booted_at)) + '）。')
    });
  }

  // 排空区块显示正在进行的 run 对应的事项标题，原始 run 标识放在灰色小字里
  function runTitles() {
    const map = {};
    if (!Y13.cap.query('run.recovery')) return map;
    Y13.api.query('projects.list', {}).data.forEach((project) => {
      Y13.api.query('project.overview', { project: project.id }).data.work_items.forEach((item) => {
        if (item.status !== 'in_progress') return;
        const data = Y13.api.query('run.recovery', { work_item: item.id }).data;
        if (data.run && data.run.id) map[data.run.id] = item.title;
      });
    });
    return map;
  }

  function drainBlock() {
    const drain = status().drain;
    if (!drain) return '';
    const titles = runTitles();
    const running = drain.running.length
      ? '<ul class="y13-list">' + drain.running.map((id) => '<li>' + Y13.esc(titles[id] || id) + '<small class="y13-muted">' + Y13.esc(id) + '</small>' + Y13.ui.status('running', '进行中') + '</li>').join('') + '</ul>'
      : '<p class="y13-muted">没有正在进行的 run</p>';
    const actions =
      (drain.state === 'none' ? Y13.ui.button({ label: '开始排空', kind: 'primary', act: 'runtime.startDrain' }) : '') +
      (drain.state === 'draining' ? Y13.ui.button({ label: '强制升级', kind: 'danger', act: 'runtime.forceUpgrade' }) : '');
    return Y13.ui.block({
      title: '排空', query: 'system.status', command: ['runtime.start_drain', 'runtime.force_upgrade'],
      // 排空在服务下一次启动时结束（应用层与接口层设计说明第 3.2 节，#731）；重新开始用项目的起点（恢复契约第 6 节第 10 行）
      subtitle: '排空期间停止开始新事项，等正在进行的 run 结束；排空在服务下一次启动时结束。强制升级时正在进行的 run 记为因升级停止，对应事项用项目的起点（采纳成果；没有时是起始文件夹快照，都没有时是空树）重新开始并排在队列最前面',
      body: Y13.ui.kv([
        ['状态', Y13.esc(DRAIN_LABELS[drain.state] || drain.state)],
        ['开始时间', drain.since ? Y13.ui.time(drain.since) : '<span class="y13-muted">—</span>'],
        ['正在进行的 run', '<span>' + drain.running.length + ' 个</span>']
      ]) + running + (actions ? '<div class="y13-row">' + actions + '</div>' : '')
    });
  }

  function retentionBlock(data) {
    const disk = data.disk;
    const total = disk.free_gb + disk.snapshots_gb + disk.workspaces_gb;
    const occupied = disk.snapshots_gb + disk.workspaces_gb;
    const warnAt = total > 0 ? (total - disk.threshold_gb) / total : 1;
    return Y13.ui.block({
      id: 'runtime-retention',
      title: '数据保留', query: 'runtime.slots', tag: 'Stage 4',
      subtitle: '可用空间低于提示阈值时，首页的状态项「磁盘空间」亮起',
      body: Y13.ui.kv([
        ['磁盘可用空间', Y13.esc(Y13.num(disk.free_gb)) + ' GB' + (disk.free_gb < disk.threshold_gb ? Y13.ui.status('failed', '低于提示阈值') : '')],
        ['提示阈值', Y13.esc(Y13.num(disk.threshold_gb)) + ' GB'],
        ['交付快照占用', Y13.esc(Y13.num(disk.snapshots_gb)) + ' GB'],
        ['工作区占用', Y13.esc(Y13.num(disk.workspaces_gb)) + ' GB'],
        ['占用比例', Y13.ui.meter(occupied, total, { warnAt }) + '<small class="y13-muted">快照与工作区合计 ' + Y13.esc(Y13.num(occupied)) + ' / ' + Y13.esc(Y13.num(total)) + ' GB</small>']
      ])
    });
  }

  function render() {
    const data = slots();
    return '<div class="y13-sys-runtime">' +
      (data ? slotBlock(data) : '') +
      drainBlock() +
      (data && data.disk ? retentionBlock(data) : '') +
      '</div>';
  }

  Y13.views.register('sys-runtime', {
    title: () => '运行与执行槽位',
    needs: { queries: ['system.status'] },
    render
  });

  Y13.actions.register('runtime.setSlots', (el) => {
    const select = document.getElementById('y13-slot-total');
    const result = Y13.run('runtime.set_slots', { total: Number(select.value), base_version: el.dataset.baseVersion });
    if (!result.accepted) return;
    redraw();
  });

  Y13.actions.register('runtime.cancelQueue', (el) => {
    const result = Y13.run('queue.cancel', { work_item_id: el.dataset.workItemId });
    if (!result.accepted) return;
    redraw();
  });

  Y13.actions.register('runtime.startDrain', () => {
    const result = Y13.run('runtime.start_drain', {});
    if (!result.accepted) return;
    redraw();
  });

  Y13.actions.register('runtime.forceUpgrade', () => {
    const result = Y13.run('runtime.force_upgrade', {});
    if (!result.accepted) return;
    redraw();
  });
})();
