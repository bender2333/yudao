// 预留入口页（设计说明第 9.5 节）：元观察、演化、经验只写所属阶段与产品结果
(function () {
  'use strict';
  const Y11 = window.Y11;

  const RESERVED = {
    meta: {
      title: '元观察', stage: 'Stage 6',
      outcome: '根据运行证据提出组织或规则变更，独立验证、限定采用并可撤销；部门之间的流转有独立的流程审查'
    },
    evolution: {
      title: '演化', stage: 'Stage 6',
      outcome: '根据运行证据提出组织或规则变更，独立验证、限定采用并可撤销；部门之间的流转有独立的流程审查'
    },
    lessons: {
      title: '经验', stage: '持续改进工作线',
      outcome: '从重复问题形成经过验证、可停用的跨任务经验，并证明收益'
    }
  };

  function entry(ctx) {
    const found = RESERVED[ctx.route.params.which];
    if (!found) throw new Error('未知预留入口：' + ctx.route.params.which);
    return found;
  }

  function render(ctx) {
    const info = entry(ctx);
    const body = Y11.ui.kv([
      ['所属阶段', Y11.esc(info.stage)],
      ['产品结果', Y11.esc(info.outcome)]
    ]) + Y11.ui.note('进入该阶段时设计。');
    return '<div class="y11-sys-reserved">' + Y11.ui.block({ title: info.title, className: 'y11-reserved', body }) + '</div>';
  }

  Y11.views.register('sys-reserved', {
    title: (ctx) => (RESERVED[ctx.route.params.which] || { title: '预留入口' }).title,
    render
  });
})();
