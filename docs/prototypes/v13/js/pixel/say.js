// 小人头顶的说话气泡（设计说明第 6 节）：小人做每一件事的时候，头顶冒出一句话说明自己现在在做什么。
// 内容只来自事件已经带着的事实（事件类型、载荷里的字段、事件说明），项目楼层与部门房间两个画面共用这一份目录。
(function () {
  'use strict';
  const Y13 = window.Y13;
  const P = Y13.pixel;
  if (!P || !P.bubble) throw new Error('say.js 需要先加载 js/pixel/engine.js');
  const PAL = P.PAL;

  const cut = (s, n) => {
    const t = String(s === undefined || s === null ? '' : s).replace(/\s+/g, ' ').trim();
    return t.length > n ? t.slice(0, n - 1) + '…' : t;
  };
  const baseName = (p) => String(p || '').split(/[\\/]/).pop();
  const deptName = (id) => (id && P.DEPTS[id] ? P.DEPTS[id].name : id || '');
  // 事件说明里冒号后面的部分（询问与回答的具体内容）
  const afterColon = (label) => {
    const m = /[：:]\s*(.+)$/.exec(String(label || ''));
    return m ? m[1] : '';
  };

  // 提案的种类（真实系统的 proposal 字段）；示例数据的提交事件没有种类，就取事件说明里「提交」后面的部分，再没有就按部门
  const PROPOSAL = {
    product_spec: '产品规格', product_decision: '产品决定', engineering_plan: '工程计划', delivery_spec: '交付说明',
    qa_review: '质检结论', collaboration_request: '询问', collaboration_response: '回答', department_guidance_response: '指导回复'
  };
  const DEFAULT_PROPOSAL = { product: '产品规格', engineering: '交付说明', quality: '质检结论', operations: '运维记录' };
  const ARTIFACT = { prd: 'PRD', box: '交付箱', defect: '返工单', release: '放行单', letter: '信件' };

  function proposalName(ev, pl) {
    if (PROPOSAL[pl.kind]) return PROPOSAL[pl.kind];
    const m = /提交(.+?)(?:[，。：:（(]|$)/.exec(String(ev.label || ''));
    return (m && m[1]) || DEFAULT_PROPOSAL[ev.department] || '提案';
  }

  const FILE_RE = /([\w\-./]+\.[A-Za-z0-9]{1,5})(?![A-Za-z0-9])/;
  const fileOf = (ev, pl) => pl.path || pl.file || (FILE_RE.exec(String(ev.label || '')) || [])[1] || null;
  // 命令：载荷里有就用载荷，没有就取事件说明末尾的英文名称
  const commandOf = (ev, pl) => pl.command || pl.name || (/([A-Za-z][\w.\-]*)\s*$/.exec(String(ev.label || '')) || [])[1] || null;

  function toolText(ev, pl) {
    const tool = String(ev.tool || pl.tool || '');
    const file = fileOf(ev, pl);
    if (tool === 'search') return '现在翻找资料' + (pl.query ? '：' + cut(pl.query, 12) : '');
    if (/^read/.test(tool)) return '现在阅读' + (file ? ' ' + cut(baseName(file), 16) : '资料');
    if (/^(edit|write)/.test(tool)) return '现在编辑' + (file ? ' ' + cut(baseName(file), 16) : '文件');
    if (tool === 'run_command' || tool === 'bash') {
      const name = commandOf(ev, pl);
      return '现在执行' + (name ? ' ' + cut(name, 14) : '命令');
    }
    if (tool === 'run_check') return '现在检查交付';
    if (/^browser/.test(tool)) return ev.department === 'quality' ? '现在试用网页' : '现在自测网页';
    if (/^(fetch|http|net|url)/.test(tool)) return '现在取回网络资料';
    if (/^mcp/.test(tool)) return '现在调用工具';
    return null;
  }

  // 没有登记在目录里的事件：拿事件说明去掉开头的主语，就是这个小人在做的事
  function fromLabel(ev) {
    const label = String(ev.label || '');
    if (!label) return null;
    const t = label.replace(/^[^，。：:、]{0,8}?(?:部门|经理|架构师|测试工程师|探索者|审查者|主程|Agent|系统|用户)(?:代表部门)?/, '');
    return cut(t || label, 26);
  }

  // 目录：事件类型 → 一句话（返回 null 表示这件事没有小人说话）。
  // 参数 (事件, 载荷, x)：x.dept 是说话的小人所在的部门，x.side 为 'to' 表示这个小人是事件里收东西的一方，x.roleName(角色) 给出角色名称
  const TEXT = {
    department_activated: () => '现在开始工作',
    context_assembled: () => '现在整理资料',
    model_requested: () => '现在思考',
    model_request_serialized: () => '现在思考',
    model_stream_progress: () => null,
    model_attempt_finished: () => '想到办法了',
    model_retry_scheduled: (ev, pl) => {
      const n = pl.n || pl.attempt || pl.attempt_no, of = pl.of || pl.max || pl.max_attempts;
      return '等一会儿再试' + (n && of ? '（第 ' + n + '/' + of + ' 次）' : '');
    },
    model_attempt_failed: () => '请求失败了',
    tool_started: toolText,
    tool_called: (ev, pl) => {
      if (!['run_command', 'bash'].includes(String(ev.tool || pl.tool || ''))) return null;
      return pl.timed_out ? '命令超时了' : pl.exit_code === 0 ? '命令通过了' : '命令没有通过';
    },
    tool_skipped: () => '这个工具没有获准，换个办法',
    proposal_submitted: (ev, pl) => '现在提交' + proposalName(ev, pl),
    proposal_rejected: () => '提案被退回，重新修改',
    spec_accepted: () => '现在盖上有效章',
    contract_accepted: () => '现在盖上有效章',
    plan_accepted: () => '现在把计划贴上白板',
    delivery_accepted: () => '现在装箱封存',
    qa_started: () => '现在开始检查',
    qa_submitted: (ev, pl) => (pl.verdict === 'release' ? '现在盖放行章' : '现在盖返工章'),
    collaboration_requested: (ev, pl, x) => {
      const asker = pl.from || ev.department;
      const q = pl.question || afterColon(ev.label);
      const tail = q ? '：' + cut(q, 14) : '';
      if (x.side === 'to' || (x.dept && x.dept !== asker)) return '收到' + deptName(asker) + '的询问' + tail;
      return '现在向' + deptName(pl.to) + '发出询问' + tail;
    },
    collaboration_responded: (ev, pl, x) => {
      // 回答方是事件所在的部门（示例数据里 from 是回答方，v8 构建约定里 to 是回答方），另一头是发问方
      const answerer = ev.department || pl.to;
      const asker = pl.from === answerer ? pl.to : pl.from;
      const a = pl.answer || afterColon(ev.label);
      const tail = a ? '：' + cut(a, 14) : '';
      if (x.side === 'to' || (x.dept && x.dept !== answerer)) return '收到' + deptName(answerer) + '的回答' + tail;
      return '现在回答' + deptName(asker) + '的询问';
    },
    collaboration_closed: () => null,
    department_guidance_received: () => '收到用户的指导',
    department_guidance_applied: () => '现在阅读指导',
    department_guidance_responded: () => '现在写指导的回复',
    compaction_recorded: () => '现在把资料整理成摘要',
    compaction_failed: () => '整理没有生效，重新整理',
    run_paused: () => '先暂停一下',
    run_failed: (ev, pl) => {
      const reason = pl.reason || pl.stopReason;
      return reason === 'cancelled' ? '事项取消了，收拾桌面' : '失败了' + (reason ? '：' + cut(reason, 12) : '');
    },
    run_done: () => '完成了！',
    x_run_interrupted: () => null,
    x_run_auto_resumed: () => '继续工作',
    x_run_stopped_for_upgrade: () => '因为升级停下，收拾桌面',
    x_action_unknown: () => '这个动作的结果不确定',
    x_decision_issued: (ev, pl) => (pl.kind === 'external_action' ? '举着申请单等待授权' : pl.kind === 'waiting_resume' ? '模型引用用不了，等你决定' : '现在送出决定单'),
    project_decision_requested: () => '现在送出决定单',
    x_decision_answered: () => '收到你的回答',
    project_decision_answered: () => '收到你的回答',
    x_remote_action_started: (ev, pl) => '现在在' + cut(pl.machine_name || '远程机器', 10) + '上执行',
    x_machine_offline: (ev, pl) => cut(pl.machine_name || '机器', 10) + '没有回应',
    x_network_fetch: () => '现在取回网络资料',
    x_mcp_called: (ev, pl) => '现在调用' + cut(pl.tool || pl.name || '工具', 12),
    x_trial_step: () => '现在试用网页',
    x_deployed: (ev, pl) => '现在部署' + (pl.version ? ' ' + pl.version : ''),
    x_rolled_back: (ev, pl) => '现在回滚' + (pl.to_version ? '到 ' + pl.to_version : ''),
    x_fault_recorded: (ev, pl) => '发现故障' + (pl.fault_id ? ' ' + pl.fault_id : ''),
    x_backup_taken: () => '现在备份数据',
    x_provider_wait_entered: () => '模型服务不可用，先等一等',
    x_provider_wait_left: () => '模型服务恢复了',
    x_role_task_assigned: (ev, pl, x) => {
      const task = pl.task ? '：' + cut(pl.task, 16) : '';
      return x.side === 'to' ? '收到任务' + task : '现在把任务交给' + (x.roleName(pl.to || ev.role) || '同事') + task;
    },
    x_role_result_returned: (ev, pl, x) => (x.side === 'to' ? '收到结果' : '现在把结果交回经理'),
    x_review_recorded: (ev, pl) => (pl.verdict === 'passed' || pl.verdict === 'pass' ? '审查通过' : '审查退回' + (pl.text ? '：' + cut(pl.text, 14) : '')),
    x_explorer_fetch: () => '现在出门查资料',
    x_replanned: () => '现在重新规划',
    x_semantic_recorded: () => '现在整理一张语义卡片',
    // 交接：交出方说把什么送给谁，接收方说收到什么
    transition: (ev, pl, x) => {
      const art = ARTIFACT[pl.artifact] || '成果';
      const receives = x.side ? x.side === 'to' : Boolean(x.dept && x.dept === pl.to && x.dept !== pl.from);
      if (receives) return '收到' + art + '，来自' + deptName(pl.from);
      return '现在把' + art + '送给' + (pl.to === 'adopted' || pl.to === 'adoption' ? '成果库' : deptName(pl.to));
    }
  };

  // ev：事件；x：{ dept（这个小人所在的部门）, side（'to' 为收东西的一方）, roleName(角色 id) → 角色名称 }
  P.say = function say(ev, x) {
    if (!ev || !ev.type) return null;
    const o = x || {};
    const ctx = { dept: o.dept || ev.department || null, side: o.side || null, roleName: (k) => (o.roleName && o.roleName(k)) || null };
    const f = TEXT[ev.type];
    if (!f) return fromLabel(ev);
    const text = f(ev, ev.payload || {}, ctx);
    return text === undefined ? fromLabel(ev) : text;
  };

  // 目录里登记的事件类型（验收脚本检查每个会引起动作的事件都有一句话）
  P.say.catalog = TEXT;

  // 一句话在头顶停留的毫秒数：读得完一句话，最长 4.6 秒
  P.sayMs = (text) => Math.min(4600, 1800 + String(text).length * 170);

  // ---------------------------------------------------------------------------
  // 画气泡：list 是 [{ a（小人的 actor）, text, kind: 'say'｜'think', until（消失的时间，最后 0.35 秒淡出）, tail（文字太长时留结尾） }]。
  // 文字按宽度折成最多两行；头顶有图标或举牌时画在它们上方；几个气泡水平重叠时依次往上抬，不互相盖住。
  // opt：{ W（画布宽度）, size（字号）, maxW（一行文字的最大宽度） }
  const layoutCache = {};
  function layout(c, text, size, maxW) {
    const key = text + '|' + size + '|' + maxW;
    if (layoutCache[key]) return layoutCache[key];
    const lines = [];
    let cur = '';
    Array.from(String(text)).forEach((ch) => {
      if (cur && P.measure(c, cur + ch, size, 500) > maxW) { lines.push(cur); cur = ch; } else cur += ch;
    });
    if (cur) lines.push(cur);
    if (lines.length > 2) {
      lines.length = 2;
      let last = lines[1];
      while (last.length > 1 && P.measure(c, last + '…', size, 500) > maxW) last = last.slice(0, -1);
      lines[1] = last + '…';
    }
    const w = Math.round(Math.max(...lines.map((l) => P.measure(c, l, size, 500))) + 8);
    if (Object.keys(layoutCache).length > 300) Object.keys(layoutCache).forEach((k) => { delete layoutCache[k]; });
    layoutCache[key] = { lines, w };
    return layoutCache[key];
  }

  P.drawSpeeches = function drawSpeeches(c, scene, list, opt) {
    const o = opt || {};
    const W = o.W || 640, size = o.size || 6, maxW = o.maxW || 84;
    const lh = size + 2;
    const rects = [];
    list.filter((it) => it.a && it.a.visible && it.text).sort((p, q) => p.a.x - q.a.x).forEach((it) => {
      const a = it.a;
      const [hx, hy] = P.headTop(scene, a);
      const text = it.tail && it.text.length > 24 ? '…' + it.text.slice(-23) : it.text;
      const lay = layout(c, text, size, maxW);
      const w = lay.w, h = lay.lines.length * lh + 3;
      const x = Math.max(2, Math.min(W - w - 2, Math.round(hx - w / 2 + 3)));
      // 头顶有状态图标或者举着的牌子时，气泡画在它们上方
      let y = hy - 9 - h - (a.icon || a.sign || (a.data && a.data.formSign) ? 14 : 0);
      while (rects.some((r) => x < r.x + r.w + 1 && x + w + 1 > r.x && y < r.y + r.h + 1 && y + h + 1 > r.y) && y > 2) y -= h + 2;
      y = Math.max(2, y);
      rects.push({ x, y, w, h });
      const fade = it.until && !scene.reduced ? Math.max(0, Math.min(1, (it.until - scene.realT) / 350)) : 1;
      c.globalAlpha = fade * (a.dim === undefined ? 1 : a.dim);
      P.bubble(c, x, y, w, h, { kind: it.kind === 'think' ? 'think' : 'say', tx: hx + 3 });
      lay.lines.forEach((line, i) => P.text(c, line, x + 4, y + 2 + i * lh + size / 2 + 0.5, { size, color: PAL.ink2 }));
      c.globalAlpha = 1;
    });
  };
})();
