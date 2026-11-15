// Troupe 风格实时循环蓝图控制台、现场窗口、成果库与事项看板（V21）
(function () {
  'use strict';
  const Y21 = window.Y21;
  const H = Y21.h, O = Y21.org, ui = Y21.ui, esc = Y21.esc, X = Y21.EXTRA;
  const DONE = ['adopted', 'open_closed', 'stopped'];
  const unfinished = (it) => Boolean(it) && !DONE.includes(it.status);
  const nm = (p, id) => O.deptName(p, id);

  // ---------------------------------------------------------------- 蓝图主题（深色终端蓝图 / 纸面图纸）
  const bpTheme = () => Y21.store.get('bpTheme', 'dark', true) || 'dark';
  const setBpTheme = (next) => { Y21.store.set('bpTheme', next, true); };

  Y21.actions.register('lp.bp', () => {
    setBpTheme(bpTheme() === 'dark' ? 'paper' : 'dark');
    Y21.rerender();
  });

  // ---------------------------------------------------------------- 模型、推理档位与实时 Braille 波形遥测
  const EFFORT_DEFAULTS = {
    product: ['中', 3],
    engineering: ['高', 4],
    quality: ['中', 3],
    operations: ['中', 3],
    architect: ['高', 4],
    lead: ['高', 4],
    explorer: ['低', 2],
    reviewer: ['高', 4],
    n1: ['中', 3],
    n2: ['中', 3]
  };

  const BRAILLE_FRAMES = [
    '⢀⣀⣀⠤⠒⠊⠉⠓⠦⣤⣶⣾⣿⣿⣶⣤⣀⠤⠒⠉⠁',
    '⣀⠤⠒⠊⠉⠓⠦⣤⣶⣾⣿⣿⣶⣤⣀⣀⠤⠒⠊⠉⠓',
    '⠤⠒⠉⠓⠦⣤⣶⣾⣿⣿⣶⣤⣀⣀⠤⠒⠊⠉⠉⠓⠦',
    '⠒⠉⠓⠦⣤⣶⣾⣿⣿⣶⣤⣀⠤⠒⠊⠉⠁⢀⣀⠤⠒',
    '⠉⠓⠦⣤⣶⣾⣿⣿⣶⣤⣀⠤⠒⠉⠁⢀⣀⠤⠒⠉⠒',
    '⠦⣤⣶⣾⣿⣿⣶⣤⣀⠤⠒⠉⠁⢀⣀⣀⠤⠒⠊⠉⠓'
  ];

  let sparkTick = 0;
  function ensureSparkTimer() {
    if (window.__y21SparkTimer) return;
    window.__y21SparkTimer = setInterval(() => {
      if (document.hidden) return;
      sparkTick = (sparkTick + 1) % BRAILLE_FRAMES.length;
      document.querySelectorAll('.js-braille').forEach((el, idx) => {
        const offset = Number(el.dataset.seed || idx) || 0;
        const f = (sparkTick + offset) % BRAILLE_FRAMES.length;
        const len = Number(el.dataset.len || 0);
        el.textContent = len ? BRAILLE_FRAMES[f].slice(0, len) : BRAILLE_FRAMES[f];
      });
      document.querySelectorAll('.js-tokps').forEach((el, idx) => {
        const base = Number(el.dataset.base || 78);
        const offset = (sparkTick + idx) % 5;
        el.textContent = (base + offset - 2) + ' tok/s';
      });
    }, 1400);
  }
  ensureSparkTimer();

  function hashSeed(str) {
    let n = 0;
    for (let i = 0; i < str.length; i += 1) n = (n * 31 + str.charCodeAt(i)) % 97;
    return n;
  }

  function latestAttempt(p, it, deptId) {
    const list = (X.attempts || []).filter((a) => a.project === p.id && a.dept === deptId && (!it || a.item === it.id));
    if (list.length) return list[0];
    return (X.attempts || []).find((a) => a.project === p.id && a.dept === deptId) || null;
  }

  function effortInfo(p, it, d) {
    if (d.who && d.who.type === 'outsourced') return { label: '由外部定', squares: 3, out: true };
    if (d.who && d.who.type === 'suborg') return { label: '按内部角色', squares: 4, sub: true };
    const cfgLvl = (X.wiring[d.id] && X.wiring[d.id].level) || null;
    const def = EFFORT_DEFAULTS[d.id] || [cfgLvl || '中', cfgLvl === '高' ? 4 : cfgLvl === '低' ? 2 : 3];
    const lvl = (p.settings && p.settings.dept && p.settings.dept[d.id] && p.settings.dept[d.id].level) || def[0];
    const sq = lvl === '极高' ? 5 : lvl === '高' ? 4 : lvl === '低' ? 2 : 3;
    return { label: lvl, squares: sq };
  }

  function nodeTele(p, it, d, status) {
    const c = (it && it.org && it.org.composed) || p.composed;
    const isSub = d.who && d.who.type === 'suborg';
    const isOut = d.who && d.who.type === 'outsourced';
    const model = isSub ? '内部 ' + (d.sub ? d.sub.depts.length : 4) + ' 角色' : (O.modelOf(p, d.id) || (X.wiring[d.id] && X.wiring[d.id].model) || '尚未选模型');
    const eff = effortInfo(p, it, d);
    const att = latestAttempt(p, it, d.id);
    const wire = X.wiring[d.id] || { window: 200000, out: 16384 };
    const round = (it && it.round) || 1;
    const active = Boolean(status && status.working);
    const hasActivity = active || Boolean(att) || (it && it.dept === d.id) || (it && DONE.includes(it.status));
    const inTok = att && att.input ? att.input : (hasActivity ? 6200 + round * 3400 + hashSeed(p.id + d.id) * 40 : 0);
    const outTok = att && att.output ? att.output : (active ? 1120 + (round * 380) : att && att.status === 'succeeded' ? 980 : 0);
    const cacheTok = att && att.cache ? att.cache : (inTok ? Math.round(inTok * 0.65) : 0);
    const pct = inTok ? Math.min(94, Math.max(4, Math.round((inTok / (wire.window || 200000)) * 100))) : 0;
    const baseTokps = 64 + (hashSeed(p.id + ':' + d.id) % 48);
    const seedIdx = hashSeed(p.id + d.id) % BRAILLE_FRAMES.length;
    const waitProvider = p.deptState && p.deptState[d.id] && p.deptState[d.id].state === 'waiting_provider';
    const fault = att && att.status === 'failed';
    const isAsking = Boolean(status && ((status.qs && status.qs.some((t) => t.startsWith('在等待'))) || status.text === '等你决定'));
    let badgeText = '空闲';
    let badgeCls = 'is-idle';
    if (it && DONE.includes(it.status)) { badgeText = it.status === 'stopped' ? '已停止' : '已结束'; badgeCls = 'is-done'; }
    else if (waitProvider || fault) { badgeText = '限流重试'; badgeCls = 'is-warn'; }
    else if (status && status.text === '等你决定') { badgeText = '等你决定'; badgeCls = 'is-ask'; }
    else if (active) { badgeText = isOut ? (d.who.agent || '外部') + ' 在做' : '进行中'; badgeCls = 'is-work'; }
    else if (isAsking) { badgeText = '等回复'; badgeCls = 'is-warn'; }
    else if (status && status.text && !/空闲|等待工作/.test(status.text)) { badgeText = '就绪'; badgeCls = 'is-ready'; }
    else if (!d.produces.length && !d.verifies) { badgeText = '接询问'; badgeCls = 'is-idle'; }
    return {
      model, isSub, isOut, eff, att, wire, inTok, outTok, cacheTok, pct,
      baseTokps, seedIdx, active, waitProvider, fault, badgeText, badgeCls,
      braille: BRAILLE_FRAMES[seedIdx],
      squaresHtml: '■'.repeat(eff.squares) + '□'.repeat(5 - eff.squares)
    };
  }

  function fmtK(n) {
    if (!n) return '0';
    return n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(n);
  }

  function nodeTelemetryHtml(p, it, c, d, status) {
    const t = nodeTele(p, it, d, status);
    const effText = t.isOut ? '外部推理' : t.eff.label;
    const wave = t.active
      ? '<span class="lp-braille js-braille" data-seed="' + t.seedIdx + '" data-len="8" aria-hidden="true">' + t.braille.slice(0, 8) + '</span>'
      : '<span class="lp-ctx-bar" aria-hidden="true"><i style="width:' + t.pct + '%"></i></span>';
    const ctxText = t.pct ? t.pct + '%' : '待命';
    return {
      badge: '<span class="lp-node-status ' + t.badgeCls + '">' + esc(t.badgeText) + '</span>',
      body:
        '<div class="lp-node-model">' + esc(t.model) + '</div>' +
        '<div class="lp-node-tele">' +
          '<span class="lp-effort" title="推理档位"><span class="lp-squares">' + t.squaresHtml + '</span><span>' + esc(effText) + '</span></span>' +
          '<span class="lp-tele-right">' + wave + '<span class="lp-ctx-pct">' + esc(ctxText) + '</span></span>' +
        '</div>'
    };
  }

  // ---------------------------------------------------------------- 现场窗口（步骤详情库 + 面板）
  const TRACE_LIB = {
    'orders:w1:engineering': [
      { task: '读取质检第 2 轮缺陷与导出需求', steps: [
        { kind: '读', text: '读取 PRD v2 与质检缺陷记录：5 万行时导出超时（62 秒）', raw: { cmd: 'read_outcome', args: 'prd v2, defect v2', exit: 0, out: '超过 5 万行时分成多个文件打成压缩包；单次耗时上限 30 秒', model: '旧实现 db.all() 一次性装入内存导致 GC 与超时，需要改成流式读取 + 分卷压缩。' } },
        { kind: '读', text: '读取 orders/export.ts、orders/money.ts 与导出测试', raw: { cmd: 'cat', args: 'orders/export.ts orders/money.ts', exit: 0, out: '184 行 · exportOrdersCsv(query, res) 使用 rows = await db.all(query)', model: '保留原有列顺序（用户指导已读），改为 async generator 分批 5000 行写流。' } }
      ] },
      { task: '改成流式分卷写出并核对用时', steps: [
        { kind: '写', text: '改写 orders/export.ts：流式游标 + 5 万行切分 zip', raw: { cmd: 'apply_patch', args: 'orders/export.ts', exit: 0, out: '1 个文件，+48 -19' } },
        { kind: '运行', text: '跑 5 万行压测与金额对分单元测试', raw: { cmd: 'npm', args: 'test -- export --bench', exit: 0, out: '14 passed, 0 failed · 50k rows exported in 4.8s', model: '耗时从 62 秒降到 4.8 秒，19.995 按分计算保持 20.00，准备提交交付 v3。' } }
      ] }
    ],
    'orders:w1:product': [
      { task: '处理质检询问并等待你的决定', steps: [
        { kind: '询问', text: '已回答质检关于超过 5 万行分文件的询问，发出 PRD v2', raw: { cmd: 'reply_inquiry', args: 'q3 (quality -> product)', exit: 0, out: '已生成 PRD v2：超过 5 万行分成多个 CSV 打压缩包' } },
        { kind: '询问', text: '就金额列格式向你发出决定卡：要不要带货币符号？', raw: { cmd: 'ask_user', args: 'item=w1', exit: 0, out: '等待你选「不带，只写数字」或「带 ¥」', model: '需要你定下输出格式后再补充 PRD 修订说明。' } }
      ] }
    ],
    'orders:w2:quality': [
      { task: '核验分页第 2 版并运行试用用例', steps: [
        { kind: '读', text: '读取工程交付第 2 版（orders/list.ts, Pager.tsx）', raw: { cmd: 'read_diff', args: 'orders/list.ts', exit: 0, out: 'pages = Math.ceil(total / 50)' } },
        { kind: '运行', text: '用浏览器工具跑翻页与条数切换用例', raw: { cmd: 'browser_run', args: 'pager-switch --viewport 1280x800', exit: 0, out: '总数为 100 时共有 2 页，第 2 页 50 条，无空页', model: '核对边界条件通过，正在写放行记录。' } }
      ] }
    ],
    'orders:w3:engineering': [
      { task: '核对银行对账规则并向产品发询问', steps: [
        { kind: '读', text: '读取项目材料「银行侧按分记账」', raw: { cmd: 'read_notes', args: 'orders/refund-rounding', exit: 0, out: '渠道侧金额单位是分，订单表 amount 字段也是分' } },
        { kind: '询问', text: '询问产品：退款金额按分取整还是按元四舍五入？', raw: { cmd: 'send_inquiry', args: 'to=product', exit: 0, out: '等待产品回答后开始改 refund/calc.ts' } }
      ] }
    ],
    'shop:w5:engineering': [
      { task: '写月度销售报表服务（等待模型限流重试）', steps: [
        { kind: '读', text: '读取 PRD：按商品类目汇总、含月环比', raw: { cmd: 'read_outcome', args: 'prd w5 v1', exit: 0, out: '按月汇总销量、销售额与上月环比变化' } },
        { kind: '运行', text: '上一次模型请求收到 HTTP 429，正在退避等待第 2 次重试', raw: { cmd: 'provider_retry', args: 'qwen3-coder-plus · attempt 2/5', exit: 429, out: '上次失败时间 14:26 · 下次计划 14:31', model: '已保留前 1 轮工作摘要，限流解除后继续。' } }
      ] }
    ],
    'shop:w6:engineering': [
      { task: '核实测试机 test-01 部署命令是否已经生效', steps: [
        { kind: '运行', text: '部署动作 9021 超时（120s），正在查询 test-01 运行版本', raw: { cmd: 'ssh_probe', args: 'test-01 · /opt/report-svc/version', exit: 1, out: '连接超时，第 1 次核实（共 2 次）；若机器离线会交回给你决定' } }
      ] }
    ],
    'logclean:w8:engineering': [
      { task: '外部 agent OpenCode 在沙盒工作区修改清理脚本', steps: [
        { kind: '读', text: '读取当前日志清理脚本与 7 天保护规则快照', raw: { cmd: 'opencode_snapshot', args: 'scripts/clean_logs.sh', exit: 0, out: '保留 -mtime -7 保护条件；新增 --max-gb 按目录占用裁剪' } },
        { kind: '写', text: '修改 clean_logs.sh 并补充干跑校验用例（OpenCode 进行中）', raw: { cmd: 'apply_patch', args: 'scripts/clean_logs.sh clean_logs_test.sh', exit: 0, out: '2 个文件修改中 · 结束后经写入入口生成快照' } }
      ] }
    ],
    'blog:w14:engineering': [
      { task: '改写静态博客首页文案并保留三个栏目', steps: [
        { kind: '读', text: '读取你发给工程的指导：保留三个栏目', raw: { cmd: 'read_guidance', args: 'item=w14', exit: 0, out: '用户指导：保留三个栏目' } },
        { kind: '写', text: '更新 content/_index.md 介绍文案与栏目导航结构', raw: { cmd: 'apply_patch', args: 'content/_index.md', exit: 0, out: '3 个栏目保持不变，介绍文案已替换' } },
        { kind: '询问', text: '向你弹出决定卡：首页要不要保留旧的访问计数？', raw: { cmd: 'ask_user', args: 'item=w14', exit: 0, out: '等待你点击「要」或「不要」' } }
      ] }
    ],
    'signup:w17:engineering': [
      { task: '实现活动报名表单与 200 人上限 / 20 人候补', steps: [
        { kind: '读', text: '读取产品回答：每场 200 人，开放 20 人候补，活动前一天关闭', raw: { cmd: 'read_inquiry', args: 'sa1, sa2', exit: 0, out: 'product 已回答两轮询问' } },
        { kind: '写', text: '写入 signup/form.ts 与并发名额锁逻辑', raw: { cmd: 'apply_patch', args: 'signup/form.ts', exit: 0, out: '1 个文件，+64 -11' } },
        { kind: '运行', text: '运行边界并发测试：第 201 位进入候补队列', raw: { cmd: 'npm', args: 'test -- signup.spec.ts', exit: 0, out: '8 passed · 第 221 位返回名额已满' } }
      ] }
    ],
    'dash:w15:engineering': [
      { task: '修复销售报表 Excel 导出列宽（第 2 轮）', steps: [
        { kind: '读', text: '读取你或观察者发现的列宽改动记录', raw: { cmd: 'read_diff', args: 'report/export.ts (round 1)', exit: 0, out: '第 1 轮曾改动 width: auto -> 18，导致长商品名被截断' } },
        { kind: '写', text: '正在计算列宽自适应范围（触发观察者振荡检测提醒）', raw: { cmd: 'apply_patch', args: 'report/export.ts', exit: 0, out: '正在修改第 42-68 行；观察者发出是否暂停确认卡' } }
      ] }
    ],
    'firmware:w11:engineering': [
      { task: '工程子组织协调：按三块板卡只读区地址实现签名校验', steps: [
        { kind: '读', text: '探索者交回调研结论：三块网关板卡 ROM 公钥基址不同', raw: { cmd: 'read_child', args: 'D-1.3 explorer', exit: 0, out: 'GW-A: 0x1000, GW-B: 0x2400, GW-C: 0x4000' } },
        { kind: '写', text: '主程在写改动 v2：验签失败先 erase(staging) 清半包再返回 -1', raw: { cmd: 'apply_patch', args: 'ota/verify.c', exit: 0, out: '已修复审查者第 1 轮打回的问题，准备重交审查' } }
      ] }
    ]
  };

  function traceFor(p, it, d, status) {
    const k = p.id + ':' + (it ? it.id : '') + ':' + d.id;
    if (TRACE_LIB[k]) return TRACE_LIB[k];
    const arrows = it ? (Y21.thread.state(p).arrows || []).filter((a) => a.item === it.id && a.from === d.id && a.work && a.work.length) : [];
    if (arrows.length) return arrows[arrows.length - 1].work;
    if (!it) {
      return [{ task: '待命中 · 等下一个事项进入', steps: [{ kind: '读', text: '目前手里没有事项；关注范围：' + (d.watches.map((x) => O.kindName(p.composed, x)).join('、') || '你的输入'), raw: { cmd: 'idle_watch', args: d.id, exit: 0, out: d.goal } }] }];
    }
    const ds = (p.deptState && p.deptState[d.id]) || {};
    const stepText = status && status.working ? (ds.text || it.title || '处理当前事项') : (status && status.text ? status.text : '等待上游成果');
    const isSub = d.who && d.who.type === 'suborg';
    const isOut = d.who && d.who.type === 'outsourced';
    const outKind = d.produces && d.produces.length ? O.kindName(it.org ? it.org.composed : p.composed, d.produces[0]) : '结论';
    const steps = [
      { kind: '读', text: '读取事项「' + it.title + '」上下文与职能要求（' + d.goal.slice(0, 32) + '）', raw: { cmd: 'load_context', args: p.id + '/' + it.id + '/' + d.id, exit: 0, out: '写入范围：' + (O.WRITE[d.write] || d.write) } },
      { kind: isOut ? '运行' : isSub ? '询问' : d.verifies ? '运行' : '写', text: stepText + (status && status.working ? '（进行中）' : ''), raw: { cmd: d.verifies ? 'verify_check' : isSub ? 'suborg_dispatch' : 'dept_step', args: d.id + ' · round ' + (it.round || 1), exit: 0, out: '当前目标产出：' + outKind } }
    ];
    if (DONE.includes(it.status)) {
      steps.push({ kind: '提交', text: '已交出「' + outKind + '」（' + (it.status === 'adopted' ? '已放行采纳' : it.status === 'open_closed' ? '开环完成' : '已结束') + '）', raw: { cmd: 'handoff', args: outKind, exit: 0, out: it.reason || '完成' } });
    }
    return [{ task: d.name + ' · ' + it.title, steps }];
  }

  function touchedFiles(p, it, d) {
    if (!it) return '未打开工作区文件';
    const s = Y21.thread.state(p);
    const files = new Set();
    (s.arrows || []).filter((a) => a.item === it.id && (a.from === d.id || a.to === d.id) && a.files).forEach((a) => a.files.forEach((f) => files.add(f)));
    if (!files.size) {
      if (p.id === 'orders' && it.id === 'w1') return 'orders/export.ts, orders/money.ts';
      if (p.id === 'firmware' && it.id === 'w11') return 'ota/verify.c, board/rom_map.h';
      if (p.id === 'shop' && it.id === 'w5') return 'report/monthly.sql, report/chart.ts';
      if (d.write === 'none') return '不写入工作区（只提交结果或回答询问）';
      if (d.write === 'check_only') return '只读核验工作区与试用用例';
      return d.write === 'workspace' ? '本项目工作区（按职能职责改文件）' : '—';
    }
    return Array.from(files).join(', ');
  }

  function livePanel(p, it, c, arrows, opts) {
    const s = Y21.thread.state(p);
    const pn = s.panel;
    const isExplicitNode = Boolean(pn && pn.type === 'node');
    if (pn && !isExplicitNode) return null; // arrow / ask / msg / item 仍使用各自的面板
    if (!isExplicitNode && s.liveOpen === false) return null;
    if (!c || !c.depts.length) return null;

    const pickedId = (isExplicitNode && c.depts.some((x) => x.id === pn.id) && pn.id) ||
      (it && c.depts.find((x) => opts.deptStatus(p, it, x).working)?.id) ||
      (it && c.depts.some((x) => x.id === it.dept) && it.dept) ||
      c.depts[0].id;
    const d = c.depts.find((x) => x.id === pickedId) || c.depts[0];
    const status = opts.deptStatus(p, it, d);
    const t = nodeTele(p, it, d, status);
    const ds = (p.deptState && p.deptState[d.id]) || {};
    const stepOpenMap = s.liveSteps || {};

    const roleTabs = c.depts.map((x) => {
      const xs = opts.deptStatus(p, it, x);
      const xt = nodeTele(p, it, x, xs);
      return '<button type="button" class="lp-live-tab' + (x.id === d.id ? ' is-on' : '') + '" data-act="lp.live-role" data-dept="' + esc(x.id) + '">' +
        '<span class="lp-dot ' + xt.badgeCls + '"></span><span>' + esc(x.name) + '</span></button>';
    }).join('');

    const attLink = t.att ? ' <button type="button" class="y21-link" data-go="#/p/' + esc(p.id) + '/observe/' + esc(t.att.id) + '">看请求 ' + esc(t.att.id.replace('r-', '')) + ' ›</button>' : '';
    const ctxLine = t.pct
      ? '<span class="lp-live-bar" aria-hidden="true"><i style="width:' + t.pct + '%"></i></span> <strong>' + t.pct + '%</strong> <span class="lp-live-dim">' + fmtK(t.inTok) + ' in · ' + fmtK(t.outTok) + ' out · ' + fmtK(t.cacheTok) + ' cache</span>' + attLink
      : '<span class="lp-live-dim">还没有模型请求</span>';

    const providerWait = (p.provider_wait || []).find((w) => w.dept === d.id);
    const remoteWait = p.remote && p.remote[d.id] && p.remote[d.id][0];
    let boundsHtml = '<span class="lp-ok-txt">工作区边界内 · 范围正常 ✓</span>';
    if (providerWait) boundsHtml = '<span class="lp-warn-txt">模型限流重试（第 ' + providerWait.attempt + '/' + providerWait.of + ' 次 · 下次 ' + esc(ui.time(providerWait.next)) + '）</span>';
    else if (remoteWait) boundsHtml = '<span class="lp-warn-txt">' + esc(remoteWait.text) + '</span> <button type="button" class="y21-link" data-go="#/p/' + esc(p.id) + '/w/' + esc(it.id) + '/recovery">动作核实 ›</button>';
    else if (d.write === 'none' || d.write === 'check_only') boundsHtml = '<span class="lp-live-dim">' + esc(O.WRITE[d.write]) + ' · 仅写自己的产物</span>';

    const tokHtml = t.active
      ? '<span class="lp-braille js-braille" data-seed="' + t.seedIdx + '">' + t.braille + '</span> <strong class="js-tokps" data-base="' + t.baseTokps + '">' + t.baseTokps + ' tok/s</strong>'
      : '<span class="lp-live-dim">' + (DONE.includes(it && it.status) ? '这一事项已结束' : t.badgeText === '限流重试' ? '等待重试窗口' : '待命中（0 tok/s）') + '</span>';

    const rawHtml = (r) => '<dl class="lp-raw">' + [['命令', r.cmd], ['参数', r.args], ['退出状态', r.exit], ['输出', r.out], ['模型记录', r.model]].filter((x) => x[1] !== undefined).map((x) => '<dt>' + x[0] + '</dt><dd>' + esc(x[1]) + '</dd>').join('') + '</dl>';
    const trace = traceFor(p, it, d, status);
    const stepsHtml = trace.map((tk, ti) => '<li class="lp-live-task"><b>' + esc(tk.task) + '</b><ul class="lp-steps">' + tk.steps.map((st0, si) => {
      const k = d.id + ':' + (it ? it.id : '0') + ':' + ti + '-' + si;
      const on = Boolean(stepOpenMap[k]);
      return '<li><button type="button" class="lp-step" data-act="lp.live-step" data-k="' + esc(k) + '" aria-expanded="' + on + '"><span class="lp-step-kind is-' + esc(st0.kind) + '">' + esc(st0.kind) + '</span><span>' + esc(st0.text) + '</span><small class="lp-step-tog">' + (on ? '收起' : '原始') + '</small></button>' + (on ? rawHtml(st0.raw) : '') + '</li>';
    }).join('') + '</ul></li>').join('');

    const innerHtml = t.isSub && ds.inner ? '<div class="lp-live-sub"><h4>内部小组实时分工</h4><ul>' + ds.inner.map((r) => '<li><b>' + esc(r.role) + '</b><span>' + esc(r.text) + '</span>' + (r.child ? '<small>' + esc(r.child) + '</small>' : '') + '</li>').join('') + '</ul><button type="button" class="y21-btn small" data-act="lp.inner" data-dept="' + esc(d.id) + '">看内部的循环图 ›</button></div>' : '';

    // 右栏：往来、给它的指导、待你决定的卡片、附带便签
    const gList = s.msgs.filter((m) => m.target === d.id && (!it || !m.item || m.item === it.id)).slice(-3);
    const guideHtml = gList.length ? '<ul class="lp-live-list">' + gList.map((m) => '<li><span>「' + esc(m.text) + '」</span><small>' + (m.readAt ? '已读 · ' + esc(ui.time(m.readAt)) : '发给它的，将在下一轮读到') + '</small></li>').join('') + '</ul>' : '<p class="lp-live-dim">还没有给这个职能单独发过指导。</p>';
    const asks = s.msgs.map((m, idx) => Object.assign({ idx }, m)).filter((m) => m.t === 'ask' && !m.answer && (!it || m.item === it.id) && (m.who === d.id || m.who === 'observer'));
    const askHtml = asks.length ? '<div class="lp-live-asks"><h4>等你决定</h4>' + asks.map((m) => {
      if (m.questions && m.questions.length) {
        const roundTxt = m.round ? ' · 第 ' + m.round + '/' + (m.maxRounds || 2) + ' 轮' : '';
        return '<div class="lp-live-ask"><p><strong>' + esc(m.title || ('需要你回答 ' + m.questions.length + ' 个问题')) + '</strong>' + (roundTxt ? '<span class="y21-muted y21-small">' + esc(roundTxt) + '</span>' : '') + '</p>' +
          '<ul class="lp-live-ask-qs">' + m.questions.map((q) => '<li>' + esc(q.prompt) + (q.recommended ? ' <span class="y21-muted">（推荐：' + esc(q.recommended) + '）</span>' : '') + '</li>').join('') + '</ul>' +
          '<div class="lp-actions"><button type="button" class="y21-btn small primary" data-act="lp.jump" data-who="' + esc(m.who || '') + '">到对话里选定 ›</button></div></div>';
      }
      return '<div class="lp-live-ask"><p>' + esc(m.text) + '</p><div class="lp-actions">' + m.options.map((opt) => '<button type="button" class="y21-btn small primary" data-act="ln.answer" data-i="' + m.idx + '" data-o="' + esc(opt) + '">' + esc(opt) + '</button>').join('') + '</div></div>';
    }).join('') + '</div>' : '';
    const relArrows = it ? arrows.filter((a) => a.from === d.id || a.to === d.id).slice(-4) : [];
    const relHtml = relArrows.length ? '<div class="lp-live-rels"><h4>本事项中与它有关的成果</h4><ul>' + relArrows.map((a) => '<li><button type="button" class="y21-link" data-act="lp.arrow" data-i="' + a.i + '">' + esc(nm(p, a.from) + ' → ' + (a.to === 'end' ? '结束' : nm(p, a.to))) + '：' + esc(a.name + (a.v ? ' v' + a.v : '')) + (a.verdict ? '（' + esc(a.verdict.by) + (a.verdict.t === 'reject' ? '打回' : '放行') + '）' : '') + '</button></li>').join('') + '</ul></div>' : '';
    const hand = p.hand && p.hand[d.id];
    const handHtml = hand && (hand.summaries.length || hand.notes) ? '<p class="lp-live-dim lp-live-hand">手边记忆：' + esc(hand.summaries.join('、') || '无摘要') + ' · 便签 ' + hand.notes + ' 条</p>' : '';

    const specialActs = [];
    if (p.id === 'pool-demo' && Y21.pool && it) {
      if (it.poolStarted) specialActs.push('<button type="button" class="y21-btn small" data-act="pool.release">停止并释放槽位</button>');
      else if (unfinished(it)) specialActs.push('<button type="button" class="y21-btn small" data-act="pool.open">分配工作单元 ›</button>');
    }
    if (p.id === 'ops-demo' && Y21.views) {
      if (d.id === 'operations') specialActs.push('<button type="button" class="y21-btn small" data-act="ops.fault-quick">模拟发现故障</button>', '<button type="button" class="y21-btn small" data-act="ops.open">运行环境 ›</button>');
    }

    return '<section class="lp-panel lp-live" data-bp="' + bpTheme() + '" aria-label="现场窗口 · live">' +
      '<div class="lp-live-head">' +
        '<div class="lp-live-title">' +
          '<span class="lp-live-kicker">现场窗口 · live</span>' +
          '<h3>' + esc(d.name) + '</h3>' +
          '<span class="lp-node-status ' + t.badgeCls + '">' + esc(t.badgeText) + '</span>' +
        '</div>' +
        '<div class="lp-live-roles" role="tablist" aria-label="切换职能现场">' + roleTabs + '</div>' +
        '<button type="button" class="lp-close" data-act="lp.live" aria-label="收起现场窗口" title="收起现场窗口">×</button>' +
      '</div>' +
      '<div class="lp-live-kv">' +
        '<div><span>goal</span><strong>' + esc(it ? it.title + ' · ' + (status.text || d.goal) : d.goal) + '</strong></div>' +
        '<div><span>agent</span><span><code>' + esc(t.model) + '</code> <span class="lp-squares">' + t.squaresHtml + '</span> ' + esc(t.eff.label) + (t.isOut ? ' · ' + esc(d.who.agent) : '') + '</span></div>' +
        '<div><span>context</span><span>' + ctxLine + '</span></div>' +
        '<div><span>touches</span><span><code>' + esc(touchedFiles(p, it, d)) + '</code></span></div>' +
        '<div><span>bounds</span><span>' + boundsHtml + '</span></div>' +
        '<div><span>tokens</span><span>' + tokHtml + '</span></div>' +
      '</div>' +
      '<div class="lp-live-cols">' +
        '<div class="lp-live-col">' +
          '<h4>实时步骤 · 可点开看原始命令与模型文字</h4>' +
          '<div class="lp-live-prompt">&gt; ' + esc(it ? it.title : '尚无进行中事项') + (ds.reason ? ' — ' + esc(ds.reason) : '') + '</div>' +
          '<ol class="lp-tasks lp-live-tasks">' + stepsHtml + '</ol>' +
          innerHtml +
        '</div>' +
        '<div class="lp-live-col">' +
          '<h4>往来与你的指导</h4>' +
          guideHtml + askHtml + relHtml + handHtml +
          '<div class="lp-actions lp-live-acts">' +
            '<button type="button" class="y21-btn small primary" data-act="lp.guide" data-dept="' + esc(d.id) + '">给' + esc(d.name) + '发指导</button>' +
            '<button type="button" class="y21-btn small" data-act="obs.dept" data-dept="' + esc(d.id) + '">本职能的模型请求 ›</button>' +
            '<button type="button" class="y21-btn small" data-go="#/p/' + esc(p.id) + '/org/d/' + esc(d.id) + '">职能详情与配置 ›</button>' +
            specialActs.join('') +
          '</div>' +
        '</div>' +
      '</div>' +
    '</section>';
  }

  Y21.actions.register('lp.live', () => {
    const p = H.project(H.pid()), s = Y21.thread.state(p);
    const wasOpen = Boolean((s.panel && s.panel.type === 'node') || s.liveOpen !== false);
    if (wasOpen) {
      s.liveOpen = false;
      if (s.panel && s.panel.type === 'node') s.panel = null;
    } else {
      s.liveOpen = true;
      s.panel = null;
    }
    Y21.thread.refresh(p);
  });

  Y21.actions.register('lp.live-role', (el) => {
    const p = H.project(H.pid()), s = Y21.thread.state(p);
    s.liveOpen = true;
    s.panel = { type: 'node', id: el.dataset.dept };
    Y21.thread.refresh(p);
  });

  Y21.actions.register('lp.live-step', (el) => {
    const p = H.project(H.pid()), s = Y21.thread.state(p);
    s.liveSteps = s.liveSteps || {};
    s.liveSteps[el.dataset.k] = !s.liveSteps[el.dataset.k];
    Y21.thread.refresh(p);
  });

  // ---------------------------------------------------------------- 成果库（顶栏 Tab 2：#/p/<id>/outcomes）
  const ocState = { filter: {}, item: {}, open: {} };

  function collectOutcomes(p) {
    const s = Y21.thread.state(p);
    const seen = new Set();
    const list = [];
    (s.arrows || []).forEach((a, i) => {
      if (a.from === 'src') return;
      const it = H.item(p, a.item);
      const isFinal = Boolean((a.verdict && a.verdict.t === 'release') || a.to === 'end' || a.name === '交付');
      const id = 'a-' + i;
      seen.add((a.item || '') + '|' + (a.name || '') + '|' + (a.v || 1) + '|' + (a.text || '').slice(0, 24));
      list.push({ id, arrowIdx: i, item: a.item, title: it ? it.title : a.item, itemObj: it, from: a.from, to: a.to, kind: a.name || '成果', v: a.v || 1, round: a.round || 1, at: a.at, text: a.text || '', prd: a.prd || null, verdict: a.verdict || null, files: a.files || [], diff: a.diff || [], work: a.work || [], isFinal });
    });
    // 兼容 work-units / preview-flows 往 s.vers 里推进去但还没生成箭头的结果
    (s.vers || []).forEach((v, vi) => {
      const sig = (v.item || '') + '|' + (v.kind || v.name || '交付') + '|' + (v.v || 1) + '|' + (v.summary || v.text || '').slice(0, 24);
      if (seen.has(sig)) return;
      const it = H.item(p, v.item);
      list.push({ id: 'v-' + vi, arrowIdx: null, item: v.item, title: it ? it.title : (v.title || '工作结果'), itemObj: it, from: v.from || (it && it.dept) || 'engineering', to: v.to || 'end', kind: v.kind || '交付', v: v.v || 1, round: v.round || (it && it.round) || 1, at: v.at || '', text: v.summary || v.text || v.name || '', verdict: v.verdict || null, files: v.files || [], diff: v.diff || [], work: [], isFinal: true });
    });
    return list.slice().reverse();
  }

  function formatDiff(lines) {
    if (!lines || !lines.length) return '';
    return '<pre class="y21-diff">' + lines.map((line) => {
      const cls = line.startsWith('+') ? 'is-add' : line.startsWith('-') ? 'is-del' : line.startsWith('@@') ? 'is-hunk' : '';
      return '<span class="y21-diff-line ' + cls + '">' + esc(line) + '</span>';
    }).join('\n') + '</pre>';
  }

  function matchingCriteria(p, oc) {
    if (!oc.verdict || oc.verdict.t !== 'release') return null;
    const rel = (p.outcomes || []).find((o) => o.item === oc.item && (o.kind === 'release' || o.kind === 'delivery') && X.criteria[o.id]);
    return rel ? X.criteria[rel.id] : null;
  }

  function outcomeVerdictBadge(p, oc) {
    const it = oc.itemObj;
    const c = (it && it.org && it.org.composed) || p.composed;
    const end = O.ending(c);
    if (oc.verdict) {
      if (oc.verdict.t === 'release') return '<span class="y21-oc-pill is-release">✓ ' + esc(oc.verdict.by) + '放行</span>';
      if (oc.verdict.t === 'reject') return '<span class="y21-oc-pill is-reject">✕ ' + esc(oc.verdict.by) + '打回</span>';
      return '<span class="y21-oc-pill is-pass">✓ ' + esc(oc.verdict.by) + '通过</span>';
    }
    if (oc.to === 'end') {
      return '<span class="y21-oc-pill is-open">◌ 开环完成：没有人核验' + (end.outsourced ? ' · 外包' : '') + '</span>';
    }
    return '<span class="y21-oc-pill is-flow">' + esc(nm(p, oc.from)) + ' → ' + esc(nm(p, oc.to)) + '</span>';
  }

  function outcomesPage(ctx, p) {
    if (X.ensure) X.ensure(p);
    const list = collectOutcomes(p);
    const cat = ocState.filter[p.id] || 'all';
    const itemF = ocState.item[p.id] || '';
    const openMap = ocState.open[p.id] || {};
    const filtered = list.filter((oc) => {
      if (cat === 'final' && !oc.isFinal) return false;
      if (cat === 'mid' && oc.isFinal) return false;
      if (itemF && oc.item !== itemF) return false;
      return true;
    });
    const relCnt = list.filter((x) => x.verdict && x.verdict.t === 'release').length;
    const openCnt = list.filter((x) => x.to === 'end' && !x.verdict).length;
    const rejCnt = list.filter((x) => x.verdict && x.verdict.t === 'reject').length;

    const filterBtns = [['all', '全部 (' + list.length + ')'], ['final', '交付与终态 (' + list.filter((x) => x.isFinal).length + ')'], ['mid', 'PRD 与缺陷记录 (' + list.filter((x) => !x.isFinal).length + ')']].map((b) =>
      '<button type="button" class="y21-btn small' + (cat === b[0] ? ' primary' : '') + '" data-act="oc.cat" data-v="' + b[0] + '">' + esc(b[1]) + '</button>'
    ).join('');
    const itemSel = '<select class="y21-select y21-oc-select" data-act="oc.item"><option value="">全部事项</option>' +
      p.items.map((it) => '<option value="' + esc(it.id) + '"' + (itemF === it.id ? ' selected' : '') + '>' + esc(it.title) + '</option>').join('') + '</select>';

    const cards = filtered.length ? filtered.map((oc) => {
      const open = Boolean(openMap[oc.id] || (filtered.length <= 4 && oc.isFinal));
      const crit = matchingCriteria(p, oc);
      const deliv = Object.values(X.delivery || {}).find((d) => oc.files.some((f) => (d.files || []).some((df) => df[0].includes(f.split('/')[1] || f))));
      const extraBody = open ? (
        (oc.prd && Y21.prdBodyHtml ? Y21.prdBodyHtml(oc.prd) : '') +
        (oc.files.length ? '<div class="y21-oc-files"><b>改动文件</b>：' + oc.files.map((f) => '<code>' + esc(f) + '</code>').join(' ') + '</div>' : '') +
        (deliv && deliv.git ? '<p class="y21-small y21-muted">提交 <code>' + esc(deliv.git.commit) + '</code> · ' + esc(deliv.git.stat) + '</p>' : '') +
        formatDiff(oc.diff) +
        (crit ? '<div class="y21-oc-crit"><b>逐条检验结果（快照 ' + esc(crit.snapshot) + '）</b>' + ui.table({
          columns: [
            { label: '编号', render: (r) => ui.code(r[0]) },
            { label: '检验项', render: (r) => esc(r[1]) },
            { label: '方式', render: (r) => esc(r[2] === 'run' ? '可执行' : r[2] === 'human' ? '人工判断' : '模型') },
            { label: '结果', render: (r) => ui.status(r[3] === 'pass' ? 'succeeded' : 'paused', r[3] === 'pass' ? '通过' : '开环记下') },
            { label: '依据', render: (r) => esc(r[4]) }
          ], rows: crit.rows
        }) + '</div>' : '') +
        (oc.work.length ? '<div class="y21-oc-work"><b>工作任务记录</b><ul>' + oc.work.map((w) => '<li>' + esc(w.task) + '（' + w.steps.length + ' 步）</li>').join('') + '</ul></div>' : '')
      ) : '';
      const locHash = '#/p/' + p.id + '?item=' + oc.item + (oc.arrowIdx !== null ? '&arrow=' + oc.arrowIdx : '');
      return '<article class="y21-oc-card' + (oc.verdict && oc.verdict.t === 'release' ? ' is-release' : oc.to === 'end' ? ' is-open' : '') + '">' +
        '<header class="y21-oc-head">' +
          '<div class="y21-oc-left">' +
            (oc.itemObj ? H.dot(oc.itemObj) : '<span class="lp-dot"></span>') +
            '<strong>' + esc(oc.kind) + ' v' + esc(oc.v) + '</strong>' +
            '<span class="y21-tag">第 ' + esc(oc.round) + ' 轮</span>' +
            outcomeVerdictBadge(p, oc) +
          '</div>' +
          '<div class="y21-oc-right">' +
            '<span class="y21-muted y21-small">' + esc(oc.title) + (oc.at ? ' · ' + esc(ui.time(oc.at)) : '') + '</span>' +
          '</div>' +
        '</header>' +
        '<p class="y21-oc-text">' + esc(oc.text || '（无文本摘要）') + '</p>' +
        '<div class="y21-oc-acts">' +
          '<button type="button" class="y21-btn small" data-act="oc.toggle" data-id="' + esc(oc.id) + '" aria-expanded="' + open + '">' + (oc.prd ? (open ? '收起完整 PRD 与差异' : '展开完整 PRD') : (open ? '收起文件与差异' : '看文件、差异与检验明细')) + '</button>' +
          '<button type="button" class="y21-btn small" data-go="' + esc(locHash) + '">在对话与循环图里定位 ›</button>' +
        '</div>' +
        extraBody +
      '</article>';
    }).join('') : ui.empty('当前筛选下没有成果。');

    return '<div class="y21-page y21-outcomes">' +
      '<div class="y21-page-head"><div class="y21-page-titles"><h1>成果库 · ' + esc(p.name) + '</h1><p class="y21-muted">所有交付版本、PRD 修订、缺陷记录与检验差异都留在这里；独立核验放行与开环完成明确区分。</p></div>' +
      '<div class="y21-page-actions">' +
        '<span class="y21-oc-pill is-release">✓ 独立放行 ' + relCnt + '</span>' +
        '<span class="y21-oc-pill is-open">◌ 开环完成 ' + openCnt + '</span>' +
        '<span class="y21-oc-pill is-reject">✕ 打回 ' + rejCnt + '</span>' +
      '</div></div>' +
      '<div class="y21-oc-bar"><div class="y21-row">' + filterBtns + '</div><div class="y21-row">' + itemSel + '</div></div>' +
      '<div class="y21-oc-list">' + cards + '</div>' +
    '</div>';
  }

  Y21.actions.register('oc.cat', (el) => { const p = H.project(H.pid()); ocState.filter[p.id] = el.dataset.v; Y21.rerender(); });
  Y21.actions.register('oc.item', (el) => { const p = H.project(H.pid()); ocState.item[p.id] = el.value; Y21.rerender(); });
  Y21.actions.register('oc.toggle', (el) => { const p = H.project(H.pid()); ocState.open[p.id] = ocState.open[p.id] || {}; ocState.open[p.id][el.dataset.id] = !ocState.open[p.id][el.dataset.id]; Y21.rerender(); });

  // ---------------------------------------------------------------- 事项与用量（顶栏 Tab 4：#/p/<id>/items）
  const itState = { status: {} };

  function itemsPage(ctx, p) {
    if (X.ensure) X.ensure(p);
    const tab = ctx.route.query.tab === 'requests' ? 'requests' : 'board';
    const subNav = '<div class="y21-subtabs" role="tablist">' +
      '<button type="button" class="y21-btn' + (tab === 'board' ? ' primary' : '') + '" data-go="#/p/' + esc(p.id) + '/items">事项列表与收敛（' + p.items.length + '）</button>' +
      '<button type="button" class="y21-btn' + (tab === 'requests' ? ' primary' : '') + '" data-go="#/p/' + esc(p.id) + '/items?tab=requests">模型请求与用量</button>' +
    '</div>';

    if (tab === 'requests') {
      return '<div class="y21-page y21-items-page">' +
        '<div class="y21-page-head"><div class="y21-page-titles"><h1>事项与用量 · ' + esc(p.name) + '</h1><p class="y21-muted">按职能、状态、事项与模型筛选本项目每一次模型请求、上下文大小与原始输出。</p></div></div>' +
        subNav +
        Y21.observe.panel(p, ctx.route.query) +
      '</div>';
    }

    const loopProj = (X.loops && X.loops[p.id] && X.loops[p.id].project) || ['项目循环', p.name, p.items.length + ' 项事项', H.dur(p.elapsed.used) + ' / ' + H.dur(p.elapsed.limit), 'converging', '', ''];
    const lsInfo = (X.loopStates && X.loopStates[loopProj[4]]) || ['运行中', 'green'];
    const statusFilter = itState.status[p.id] || 'all';
    const byStatus = (st0) => p.items.filter((x) => st0 === 'all' ? true : st0 === 'working' ? unfinished(x) : x.status === st0);
    const visible = byStatus(statusFilter);
    const currentCore = O.coreDigest(p.composed);
    const poolSummary = p.composed.rotation === 'pool' && Y21.pool ? '<div class="y21-items-pool">' + Y21.pool.summary(p) + '</div>' : '';

    const summaryBar = ui.block({
      title: '项目循环与资源上限',
      actions: ui.status(lsInfo[1] === 'red' ? 'failed' : lsInfo[1] === 'amber' ? 'paused' : 'running', lsInfo[0]),
      body: ui.kv([
        ['累计用时与上限', esc(H.dur(p.elapsed.used)) + ' / ' + esc(H.dur(p.elapsed.limit)) + ui.meter(p.elapsed.used, p.elapsed.limit)],
        ['并发执行槽位', '占用 ' + p.slots.used + ' / 上限 ' + p.slots.limit + (p.slots.waiting ? ' · 排队 ' + p.slots.waiting + ' 件' : '')],
        ['循环说明', esc(loopProj[6] || '各事项按建立时冻结的组织推进。')]
      ])
    });

    const filters = [['all', '全部'], ['working', '未结束'], ['adopted', '已放行采纳'], ['open_closed', '开环完成'], ['stopped', '已停止']].map((b) =>
      '<button type="button" class="y21-btn small' + (statusFilter === b[0] ? ' primary' : '') + '" data-act="it.filter" data-v="' + b[0] + '">' + esc(b[1]) + ' (' + byStatus(b[0]).length + ')</button>'
    ).join('');

    const itemCards = visible.length ? visible.map((it) => {
      const sameOrg = !it.org || it.org.core === currentCore;
      const c = (it.org && it.org.composed) || p.composed;
      const curDept = it.dept ? nm(p, it.dept) : '—';
      const acts = [
        '<button type="button" class="y21-btn small primary" data-go="#/p/' + esc(p.id) + '?item=' + esc(it.id) + '">在对话与循环图里看 ›</button>',
        c.depts.length > 1 ? '<button type="button" class="y21-btn small" data-go="#/p/' + esc(p.id) + '?item=' + esc(it.id) + '&seq=1">看时序经过 ›</button>' : '',
        it.org ? '<button type="button" class="y21-btn small" data-go="#/p/' + esc(p.id) + '/w/' + esc(it.id) + '/org">冻结的组织 (' + esc(it.org.version || 'v1') + ') ›</button>' : '',
        it.round > 0 ? '<button type="button" class="y21-btn small" data-go="#/p/' + esc(p.id) + '/w/' + esc(it.id) + '/recovery">恢复与动作核实 ›</button>' : ''
      ].join('');
      return '<article class="y21-it-card">' +
        '<header class="y21-it-head">' +
          '<div class="y21-row">' + H.dot(it) + ' <strong>' + esc(it.title) + '</strong> ' + H.status(it) +
            '<span class="y21-tag">' + (it.round ? '第 ' + it.round + ' / ' + it.round_limit + ' 轮' : '未运行') + '</span>' +
            '<span class="y21-tag">所在职能：' + esc(curDept) + '</span>' +
            (sameOrg ? '' : '<span class="y21-tag is-warn">按旧组织跑</span>') +
          '</div>' +
          '<span class="y21-small y21-muted">' + (it.limit ? esc(H.dur(it.used)) + ' / ' + esc(H.dur(it.limit)) : '') + '</span>' +
        '</header>' +
        (it.limit ? ui.meter(it.used, it.limit) : '') +
        (it.reason ? '<p class="y21-small">' + esc(it.reason) + '</p>' : '') +
        '<div class="y21-it-loops">' + Y21.observe.loops(p, it) + '</div>' +
        '<div class="y21-actions">' + acts + '</div>' +
      '</article>';
    }).join('') : ui.empty('这一筛选下没有事项。');

    return '<div class="y21-page y21-items-page">' +
      '<div class="y21-page-head"><div class="y21-page-titles"><h1>事项与用量 · ' + esc(p.name) + '</h1><p class="y21-muted">所有事项状态、冻结组织版本、收敛判断与模型调用汇总。</p></div></div>' +
      subNav + summaryBar + poolSummary +
      '<div class="y21-row y21-it-filters">' + filters + '</div>' +
      '<div class="y21-it-list">' + itemCards + '</div>' +
    '</div>';
  }

  Y21.actions.register('it.filter', (el) => { const p = H.project(H.pid()); itState.status[p.id] = el.dataset.v; Y21.rerender(); });

  // ---------------------------------------------------------------- 注册视图与导出
  Y21.views.register('outcomes', { render: outcomesPage });
  Y21.views.register('items', { render: itemsPage });
  Y21.leanViews.outcomes = { render: outcomesPage };
  Y21.leanViews.items = { render: itemsPage };

  Y21.troupe = {
    bpTheme,
    setBpTheme,
    nodeTele,
    nodeTelemetryHtml,
    livePanel,
    collectOutcomes
  };
})();
