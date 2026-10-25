// 工具与扩展页（设计说明第 9.4 节；网络取回与 MCP 工具设计说明第 11.3 节）：只读汇总。网络取回列最近的取回记录，
// MCP 列各项目的服务器、最近一次状态与工具；修改 MCP 服务器在项目设置页。浏览器与 computer use、只读观察者照旧
(function () {
  'use strict';
  const Y12 = window.Y12;
  const DEPT = { product: '产品', engineering: '工程', quality: '质检', operations: '运维' };

  function registry() { return Y12.api.query('tools.registry').data; }

  function projectName(id) {
    const project = Y12.api.query('projects.list', {}).data.find((item) => item.id === id);
    return project ? project.name : id;
  }

  function toolsTable(tools) {
    return Y12.ui.table({
      columns: [
        { key: 'name', label: '工具', render: (row) => Y12.ui.code(row.name) },
        { key: 'description', label: '说明', render: (row) => Y12.esc(row.description || '') }
      ],
      rows: tools
    });
  }

  function networkBlock(data) {
    const recent = Y12.ui.table({
      columns: [
        { key: 'at', label: '时间', render: (row) => Y12.esc(Y12.ui.time(row.at)) },
        { key: 'url', label: '地址', render: (row) => Y12.ui.code(row.url) },
        { key: 'project_id', label: '项目', render: (row) => Y12.esc(projectName(row.project_id)) },
        { key: 'result', label: '结果' }
      ],
      rows: data.network.recent,
      empty: '没有取回记录'
    });
    return Y12.ui.block({
      title: '网络取回', query: 'tools.registry',
      subtitle: data.network.scope,
      body: '<h3 class="y12-h3">最近的取回记录</h3>' + recent
    });
  }

  function mcpBlock(data) {
    const sections = data.mcp.map((server) =>
      '<section class="y12-mcp"><h3 class="y12-h3">' + Y12.esc(server.name) + ' ' + Y12.ui.tag(projectName(server.project_id)) + '</h3>' +
        Y12.ui.kv([
          ['连接方式', Y12.ui.code(server.transport)],
          ['可以使用的部门', Y12.esc(server.departments.map((d) => DEPT[d] || d).join('、'))],
          ['最近一次状态', Y12.ui.status(server.last.ok ? 'succeeded' : 'failed', server.last.text) + ' <span class="y12-muted">' + Y12.esc(Y12.ui.time(server.last.at)) + '</span>']
        ], 'is-rows') +
        toolsTable(server.tools) +
        '<div class="y12-row">' + Y12.ui.button({ label: '在项目设置中修改', kind: 'small', go: Y12.paths.settings(server.project_id) }) + '</div></section>').join('');
    return Y12.ui.block({
      title: 'MCP 工具', query: 'tools.registry',
      subtitle: '各项目在设置中写明的 MCP 服务器：怎样启动或连接、哪些部门可以使用；服务器提供的工具全部直接提供给这些部门',
      body: sections || Y12.ui.empty('还没有项目接入 MCP 服务器')
    });
  }

  function browserBlock(data) {
    return Y12.ui.block({
      title: '浏览器工具', query: 'tools.registry', tag: '3.2D',
      subtitle: data.name + '：' + data.note,
      body: toolsTable(data.tools)
    });
  }

  function computerUseBlock(data) {
    return Y12.ui.block({
      title: 'computer use', query: 'tools.registry', tag: '3.2D',
      subtitle: data.name + '：' + data.note + '（虚拟屏幕 ' + data.screen.width + ' × ' + data.screen.height + '，' + data.screen.place + '）',
      body: toolsTable(data.tools)
    });
  }

  function observersBlock(data) {
    return Y12.ui.block({
      title: '只读观察者', query: 'tools.registry', tag: 'Stage 5',
      subtitle: data.note,
      body: Y12.ui.table({
        columns: [
          { key: 'name', label: '观察者' },
          { key: 'scope', label: '订阅范围' }
        ],
        rows: data.items,
        empty: '还没有登记的观察者'
      })
    });
  }

  function render() {
    const data = registry();
    return '<div class="y12-sys-tools">' +
      networkBlock(data) +
      mcpBlock(data) +
      (data.browser ? browserBlock(data.browser) : '') +
      (data.computer_use ? computerUseBlock(data.computer_use) : '') +
      (data.observers ? observersBlock(data.observers) : '') +
      '</div>';
  }

  Y12.views.register('sys-tools', {
    title: () => '工具与扩展',
    needs: { queries: ['tools.registry'] },
    render
  });
})();
