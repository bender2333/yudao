// V14 只替换模型管理，外壳、导航和画面复用 V13；本轮交互全部留在内存。
(function () {
  'use strict';
  const Y = window.Y13;
  const memory = new Map();
  Y.store = {
    get: (key, fallback) => memory.has(key) ? structuredClone(memory.get(key)) : fallback,
    set: (key, value) => memory.set(key, structuredClone(value))
  };
  Y.level.set('ui');
  window.Y14 = Y;
  if (!location.hash) history.replaceState(null, '', '#/sys/models');
  let firstRender = true;
  Y.bus.on('content-rendered', () => {
    document.querySelectorAll('.y13-proto-chip').forEach((node) => { node.textContent = 'v14 原型'; });
    document.title = document.title.replace('v13', 'v14');
    if (firstRender) {
      firstRender = false;
      if (document.querySelector('[data-act="tb.toggle"][aria-expanded="true"]')) Y.actions.run('tb.toggle');
    }
  });
})();
