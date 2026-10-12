// 连接设置（设计说明第 3.4 节）：本机或局域网地址、访问令牌与接口版本
(function () {
  'use strict';
  const Y8 = window.Y8;

  function versionRow(dep) {
    const client = Y8.CLIENT_API_VERSION;
    const same = dep.api_version === client;
    return Y8.ui.kv([
      ['控制主机的接口版本', Y8.ui.code(String(dep.api_version)) + (same ? Y8.ui.status('succeeded', '与客户端相同') : Y8.ui.status('failed', '与客户端不同'))],
      ['客户端的接口版本', Y8.ui.code(String(client))],
      ['连接日志', Y8.ui.code(dep.log_id)],
      ['本次启动', Y8.ui.code(dep.boot_id) + ' · 服务版本 ' + Y8.esc(dep.service_version)],
      ['访问方式', dep.access === 'lan' ? '局域网内使用' : Y8.esc(dep.access)]
    ]);
  }

  function render() {
    const dep = Y8.api.capabilities().deployment;
    const address = Y8.ui.block({
      title: '服务地址', query: null,
      body: '<div class="y8-form">' +
        '<label class="y8-field"><span>本机或局域网地址</span><input class="y8-input" type="url" id="y8-connect-address" data-draft="connect.address" value="http://127.0.0.1:8765" placeholder="http://127.0.0.1:8765"><small class="y8-muted">本机用回环地址；其它设备用控制主机的局域网地址。</small></label>' +
        '<label class="y8-field"><span>访问令牌</span><input class="y8-input" type="password" value="" placeholder="局域网内使用期间不需要" disabled><small class="y8-muted">局域网内使用期间不需要（TODO：接入控制主机以后设计）。</small></label>' +
        '<div class="y8-row">' + Y8.ui.button({ label: '连接', kind: 'primary', act: 'connect.submit' }) + '</div>' +
        '</div>'
    });
    const versions = Y8.ui.block({ title: '接口版本', query: null, body: versionRow(dep) });
    return '<div class="y8-connect">' + address + versions + '</div>';
  }

  Y8.views.register('connect', {
    title: () => '连接设置',
    render
  });

  Y8.actions.register('connect.submit', () => {
    Y8.ui.toast('原型：连接按钮只显示提示，不改变连接', 'ok');
  });
})();
