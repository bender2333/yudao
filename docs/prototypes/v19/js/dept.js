// 部门页（原来的房间）：角色在做什么、实时的模型输出、手边的摘要与笔记、等待模型服务、远程结果未知
(function () {
  'use strict';
  const Y19 = window.Y19;
  const esc = Y19.esc;
  const H = Y19.h;
  const ui = Y19.ui;

  // 假的模型输出：逐字出现，到头以后停在最后
  const LIVE = {
    product: '读到工程的询问：退款金额取整按分还是按元。\n查支付渠道的对账规则：渠道侧按分记账，订单表金额字段单位是分。\n结论：按分取整，不做元级舍入。\n正在把这条写进「退款金额取整」的 PRD 第 2 版……',
    engineering: '读取 orders/export.ts，现在只有 JSON 导出。\n计划：新增 exportOrdersCsv(range)，按创建时间倒序，最多 5 万行。\n文件名 orders-日期.csv，UTF-8 带 BOM，Excel 打开不乱码。\n正在写 orders/export-csv.ts 和对应的单元测试……',
    quality: '拿到分页交付第 2 版，先对照缺陷记录第 1 条：翻到最后一页再切换每页条数。\n运行试用用例：翻页 → 切换每页条数 → 期望回到第 1 页。\n用例通过。继续核验：筛选条件翻页后是否保留……',
    'logclean|engineering': '外部 agent 拿到一份没有历史的快照：日志目录按天切分，最近 7 天的不能动。\n正在写按目录大小清理的开关，超过阈值才删最旧的文件。\n改完会交回快照与差异……',
    'blog|engineering': '读取首页文案，现在的第一句是旧站点的口号。\n改成新站点的介绍，保留三个栏目链接。\n正在检查改动后链接是否还指向存在的页面……',
    'dash|engineering': '读取汇总查询的结果结构。\n计划按月、按类目导出成 CSV，带 BOM 让 Excel 直接打开。\n正在写导出函数和自测……',
    'signup|engineering': '产品回答：开放候补，最多 20 人。\n正在把候补状态加进报名表单，人数满了显示候补入口……',
    'firmware|engineering': '工程架构师：把签名校验拆成三步：验签、存储公钥、升级前检查。\n主程：先写验签函数，用只读区里的公钥；单元测试覆盖签名被改一个字节的情形。\n审查者：等主程的改动。',
    'firmware|n1': '在第 3 块板子上跑启动冒烟：验签通过，但看门狗在 1.2 秒后复位，怀疑是外设初始化顺序。\n记录串口输出，写进适配包的回执……'
  };
  const LAST = {
    engineering: '读取 reports/monthly.ts 的现有查询。\n计划按商品类目汇总，加环比列。\n请求模型服务时被限流，等待重试……'
  };

  let timer = null;

  function liveText(p, d, s) {
    if (s.state === 'running') return { text: LIVE[p.id + '|' + d] || LIVE[d] || '正在工作……', live: true };
    return { text: LAST[d] || '（没有输出）', live: false };
  }

  function roleBlock(p, d, s) {
    const items = s.items.map((id) => H.item(p, id)).filter(Boolean);
    const stateLabel = { running: ['running', '工作中'], idle: ['idle', '空闲'], waiting_provider: ['waiting_provider', '等待模型服务'], interrupted: ['interrupted', '中断'], waiting_work: ['waiting', '等待工作'] }[s.state];
    return ui.block({
      title: '角色在做什么', body: ui.kv([
        ['角色', esc(s.role) + ' <small class="y19-muted">· 模型 ' + esc(s.model) + '</small>'],
        ['状态', ui.status(stateLabel[0], stateLabel[1])],
        ['在做什么', esc(s.text) + ' ' + H.src('dept-' + p.id + '-' + d)],
        ['原因', esc(s.reason)],
        s.progress ? ['进度', esc(s.progress)] : null,
        ['手上的事项', items.length ? items.map((i) => H.dot(i) + ' ' + H.link('#/p/' + p.id + '/w/' + i.id, i.title)).join('<br>') : '没有']
      ], 'y19-card-kv')
    });
  }

  // 角色指向子组织时，部门页显示内部的角色在做什么，并链到子事项
  function innerBlock(p, d, s, dd) {
    if (!dd || !dd.who || dd.who.type !== 'suborg') return '';
    if (!s.inner) return ui.block({ title: '内部的角色在做什么', body: ui.empty('内部的角色现在都空闲') });
    const label = { running: ['running', '工作中'], idle: ['idle', '空闲'], waiting_work: ['waiting', '等待工作'] };
    return ui.block({ id: 'dept-inner', title: '内部的角色在做什么', subtitle: '这个部门由子组织（' + dd.sub.formName + '）来做；一轮工作开一个子事项，结果作为提案回到这一层',
      actions: ui.button({ label: '打开内部', kind: 'small', go: '#/p/' + p.id + '/org/s/' + d }),
      body: ui.table({ columns: [{ label: '角色', render: (r) => '<strong>' + esc(r.role) + '</strong>' }, { label: '状态', render: (r) => ui.status(label[r.state][0], label[r.state][1]) },
        { label: '在做什么', render: (r) => esc(r.text) }, { label: '子事项', render: (r) => (r.child ? esc(r.child) : '<span class="y19-muted">—</span>') }], rows: s.inner }) });
  }

  function handBlock(p, d) {
    const h = (p.hand && p.hand[d]) || { summaries: [], notes: 0 };
    return ui.block({
      title: '手边', subtitle: '这个部门自己留着用的摘要和笔记',
      body: ui.kv([['摘要', h.summaries.length + ' 份'], ['笔记', h.notes + ' 条']], 'is-inline') +
        (h.summaries.length ? '<details class="y19-details"><summary>看摘要的标题</summary><ul class="y19-list">' + h.summaries.map((t) => '<li>' + esc(t) + '</li>').join('') + '</ul></details>' : '')
    });
  }

  function waitBlock(p, d, s) {
    const pw = p.provider_wait.filter((w) => w.dept === d);
    const remote = ((p.remote || {})[d]) || [];
    const model = pw.length ? pw.map((w) => {
      const it = H.item(p, w.item);
      return '<div class="y19-callout is-wait">' + ui.status('waiting_provider', '等待模型服务') + ' <b>' + H.dot(it) + ' ' + esc(it.title) + '</b>：' + ui.code(w.model) + ' 返回「' + esc(w.category) + '」，已等 ' + esc(H.waited(w.since)) +
        '。第 ' + w.attempt + ' 次重试，共 ' + w.of + ' 次，下一次 ' + esc(ui.time(w.next)) + ' ' + H.src('provider-' + w.item) + '</div>';
    }).join('') : '<p class="y19-muted">没有在等模型服务。</p>';
    const rem = remote.length ? remote.map((r) => {
      const it = H.item(p, r.item);
      return '<div class="y19-callout is-unknown">' + ui.status('unknown', '远程结果未知') + ' <b>' + H.dot(it) + ' ' + esc(it.title) + '</b>：' + esc(r.action) + '。' + esc(r.text) + ' ' + H.src('remote-' + r.item) + '</div>';
    }).join('') : '<p class="y19-muted">没有结果未知的远程动作。</p>';
    return ui.block({ title: '在等什么', body: '<h3 class="y19-h3">模型服务</h3>' + model + '<h3 class="y19-h3">远程动作</h3>' + rem });
  }

  Y19.views.register('dept', {
    render(ctx, p) {
      const d = ctx.route.params.dept;
      const s = p.deptState[d];
      if (!s) return '<div class="y19-gate"><h1>找不到部门</h1><p class="y19-muted">这个项目的定义里没有这个部门。</p></div>';
      const lv = liveText(p, d, s);
      const desk = Y19.W().desktop && Y19.W().desktop.dept === d && Y19.W().desktop.project === p.id;
      const asks = p.asks.filter((a) => a.from === d || a.to === d);
      const outs = p.outcomes.filter((o) => o.from === d).slice(-5).reverse();
      const old = p.onlyOld.includes(d);
      const dd = p.composed.depts.find((x) => x.id === d);
      return '<div class="y19-page"><div class="y19-page-head"><div class="y19-page-titles"><h1>' + esc(H.dept(d)) + '部门' + (old ? ' ' + ui.tag('只在旧组织里', 'changed') : '') + '</h1><p class="y19-muted">' + esc(p.name) + '</p></div>' +
        '<div class="y19-page-actions">' + (old ? '' : ui.button({ label: '看它怎么安排的', kind: 'small', go: '#/p/' + p.id + '/org/d/' + d })) + '</div></div>' +
        (old ? ui.note('现在的组织已经没有这个部门，还有事项在按建立时的旧组织跑，它们跑完以后这个部门就不再出现。', 'warn') : '') +
        roleBlock(p, d, s) + innerBlock(p, d, s, dd) +
        (desk ? ui.block({ title: '桌面', body: ui.note('这个部门正在使用本机桌面：' + esc(Y19.W().desktop.what) + '。已用 ' + esc(H.waited(Y19.W().desktop.since)) + '。要结束，点页面最上面一条里的「停止使用」。', 'warn') }) : '') +
        ui.block({ title: lv.live ? '实时的模型输出' : '最后一段模型输出', subtitle: lv.live ? '模型正在写，字一个一个出来' : '这个部门现在没有在输出', body: '<pre class="y19-pre y19-live" id="live-out" data-full="' + esc(lv.text) + '" data-live="' + lv.live + '"></pre>' }) +
        waitBlock(p, d, s) + handBlock(p, d) +
        ui.block({ title: '相关的询问', body: asksTableLite(p, asks) }) +
        ui.block({ title: '这个部门最近交出的成果', body: ui.table({
          columns: [
            { label: '种类', render: (o) => '<span class="y19-okind is-' + o.kind + '">' + esc(Y19.OUTCOME_KINDS[o.kind]) + '</span>' },
            { label: '内容', render: (o) => esc(o.text) }, { label: '时间', render: (o) => esc(ui.time(o.at)) }, { label: '来源', render: (o) => H.src(o.id) }
          ], rows: outs, empty: '还没有交出过成果' }) }) + '</div>';
    },
    mount(ctx, root) {
      const el = root.querySelector('#live-out');
      if (!el) return;
      const full = el.dataset.full;
      if (el.dataset.live !== 'true') { el.textContent = full; return; }
      let n = 0;
      timer = setInterval(() => {
        if (!el.isConnected) { clearInterval(timer); return; }
        n = n >= full.length + 25 ? 0 : n + 2;
        el.textContent = full.slice(0, Math.min(n, full.length)) + (n < full.length ? '▌' : '');
      }, 70);
    },
    unmount() { if (timer) clearInterval(timer); timer = null; }
  });

  function asksTableLite(p, asks) {
    return ui.table({
      columns: [
        { label: '谁问谁', render: (a) => esc(H.dept(a.from)) + ' → ' + esc(H.dept(a.to)) },
        { label: '问题', render: (a) => esc(a.text) + ' ' + H.src(a.key) },
        { label: '已等待', render: (a) => esc(H.waited(a.at)) }
      ], rows: asks, empty: '没有进行中的询问'
    });
  }
})();
