// 工具与扩展页（设计说明第 9.4 节）：网络取回、MCP 工具、浏览器与 computer use、只读观察者与准入钩子
(function () {
  'use strict';
  const Y8 = window.Y8;

  function registry() { return Y8.api.query('tools.registry').data; }

  function projectName(id) {
    const project = Y8.api.query('projects.list', {}).data.find((item) => item.id === id);
    return project ? project.name : id;
  }

  function toolsTable(tools) {
    return Y8.ui.table({
      columns: [
        { key: 'name', label: '工具', render: (row) => Y8.ui.code(row.name) },
        {
          key: 'recovery', label: '恢复约定（结果未知时怎样核实）',
          render: (row) => (row.recovery ? Y8.esc(row.recovery) : '<span class="y8-muted">没有恢复约定</span>')
        },
        { key: 'retry', label: '重试', render: (row) => (row.retry === '可以重复' ? Y8.esc(row.retry) : Y8.ui.tag('不自动重试', 'warn')) }
      ],
      rows: tools
    });
  }

  function networkBlock(data) {
    const grants = Y8.ui.table({
      columns: [
        { key: 'project_id', label: '项目', render: (row) => Y8.esc(projectName(row.project_id)) },
        { key: 'scope', label: '授权范围' },
        { key: 'approval', label: '超出范围时' }
      ],
      rows: data.network.grants,
      empty: '还没有项目登记网络取回授权'
    });
    const recent = Y8.ui.table({
      columns: [
        { key: 'at', label: '时间', render: (row) => Y8.esc(Y8.ui.time(row.at)) },
        { key: 'url', label: '地址', render: (row) => Y8.ui.code(row.url) },
        { key: 'project_id', label: '项目', render: (row) => Y8.esc(projectName(row.project_id)) },
        { key: 'result', label: '结果' }
      ],
      rows: data.network.recent,
      empty: '没有取回记录'
    });
    return Y8.ui.block({
      title: '网络取回', query: 'tools.registry',
      subtitle: data.network.scope,
      body: '<h3 class="y8-h3">各项目的授权</h3>' + grants + '<h3 class="y8-h3">最近的取回记录</h3>' + recent
    });
  }

  function mcpBlock(data) {
    const sections = data.mcp.map((server) =>
      '<section class="y8-mcp"><h3 class="y8-h3">' + Y8.esc(server.name) + '</h3>' + toolsTable(server.tools) + '</section>').join('');
    return Y8.ui.block({
      title: 'MCP 工具', query: 'tools.registry',
      subtitle: '按工具逐项声明恢复约定；没有恢复约定的工具不自动重试',
      body: sections || Y8.ui.empty('还没有接入 MCP 服务')
    });
  }

  function browserBlock(data) {
    return Y8.ui.block({
      title: '浏览器工具', query: 'tools.registry', tag: '3.2D',
      subtitle: data.name + '：' + data.note,
      body: toolsTable(data.tools)
    });
  }

  function computerUseBlock(data) {
    return Y8.ui.block({
      title: 'computer use', query: 'tools.registry', tag: '3.2D',
      subtitle: data.name + '：' + data.note + '（虚拟屏幕 ' + data.screen.width + ' × ' + data.screen.height + '，' + data.screen.place + '）',
      body: toolsTable(data.tools)
    });
  }

  function observersBlock(data) {
    return Y8.ui.block({
      title: '只读观察者', query: 'tools.registry', tag: 'Stage 5',
      subtitle: data.note,
      body: Y8.ui.table({
        columns: [
          { key: 'name', label: '观察者' },
          { key: 'scope', label: '订阅范围' }
        ],
        rows: data.items,
        empty: '还没有登记的观察者'
      })
    });
  }

  function hooksBlock(data) {
    return Y8.ui.block({
      title: '准入钩子', query: 'tools.registry', tag: 'Stage 6',
      subtitle: '准入钩子：只能收紧的许可规则，不修改内核增加一项检查',
      body: Y8.ui.empty(data.hooks.note)
    });
  }

  function render() {
    const data = registry();
    const pending = Y8.ui.note('<strong>' + Y8.esc(data.design_note) + '</strong>：这一页的依据是路线图与 Stage 3 计划的工作包说明，进入各工作包时细化。', 'warn');
    return '<div class="y8-sys-tools">' + pending +
      networkBlock(data) +
      mcpBlock(data) +
      (data.browser ? browserBlock(data.browser) : '') +
      (data.computer_use ? computerUseBlock(data.computer_use) : '') +
      (data.observers ? observersBlock(data.observers) : '') +
      hooksBlock(data) +
      '</div>';
  }

  Y8.views.register('sys-tools', {
    title: () => '工具与扩展',
    needs: { queries: ['tools.registry'] },
    render
  });
})();
