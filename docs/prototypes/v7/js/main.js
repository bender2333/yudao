// 启动：全部文件注册完成后渲染当前路径；没有路径时进入文本报表工具的概览
(function () {
  'use strict';

  const Y7 = window.Y7;
  if (!location.hash || location.hash === '#' || location.hash === '#/') {
    history.replaceState(null, '', '#/p/p-report/overview');
  }
  Y7.start();
})();
