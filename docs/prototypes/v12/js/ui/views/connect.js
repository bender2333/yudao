// 连接设置（设计说明第 3.4 节）：本机或局域网地址、访问令牌与接口版本
(function () {
  'use strict';
  const Y12 = window.Y12;

  function versionRow(dep) {
    const client = Y12.CLIENT_API_VERSION;
    const same = dep.api_version === client;
    return Y12.ui.kv([
      ['服务的接口版本', Y12.ui.code(String(dep.api_version)) + (same ? Y12.ui.status('succeeded', '与页面相同') : Y12.ui.status('failed', dep.api_version > client ? '比页面新' : '比页面旧'))],
      ['页面的接口版本', Y12.ui.code(String(client))],
      ['连接日志', Y12.ui.code(dep.log_id)],
      ['本次启动', Y12.ui.code(dep.boot_id) + ' · 服务版本 ' + Y12.esc(dep.service_version)],
      ['访问方式', dep.access === 'lan' ? '局域网内使用' : Y12.esc(dep.access)]
    ]);
  }

  function render() {
    const dep = Y12.api.capabilities().deployment;
    const address = Y12.ui.block({
      title: '服务地址', query: null,
      body: '<div class="y12-form">' +
        '<label class="y12-field"><span>本机或局域网地址</span><input class="y12-input" type="url" id="y12-connect-address" data-draft="connect.address" value="http://127.0.0.1:8765" placeholder="http://127.0.0.1:8765"><small class="y12-muted">本机用回环地址；其它设备用控制主机的局域网地址。</small></label>' +
        '<label class="y12-field"><span>访问令牌</span><input class="y12-input" type="password" value="" placeholder="局域网内使用期间不需要" disabled><small class="y12-muted">局域网内使用期间不需要（TODO：接入控制主机以后设计）。</small></label>' +
        '<div class="y12-row">' + Y12.ui.button({ label: '连接', kind: 'primary', act: 'connect.submit' }) + '</div>' +
        '</div>'
    });
    const versions = Y12.ui.block({ title: '接口版本', query: null, body: versionRow(dep) });
    return '<div class="y12-connect">' + address + versions + '</div>';
  }

  Y12.views.register('connect', {
    title: () => '连接设置',
    render
  });

  Y12.actions.register('connect.submit', () => {
    Y12.ui.toast('原型：连接按钮只显示提示，不改变连接', 'ok');
  });
})();
