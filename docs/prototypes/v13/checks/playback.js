// 画面合同与播放时间线的检查（画面与播放设计说明第 8 节）：
//   H3   画面层（js/pixel/）不导入 Yudao 的任何代码，也不认 Yudao 的事件种类
//   覆盖 能力清单里的每种事件，在楼、楼层、房间三个场景里要么翻成动作（或实时内容），要么列在「不画」里并写理由
//   H8   落后有上限：确定的时钟下，堆积的事件到达以后，画面上状态的位置落后最新到达的状态不超过上限（三个场景都查）
//   H9   关键动作不丢：堆积时关键一级的动作全部开始演
//   节奏 状态等它之前的动作演完再上画面；决定卡片与流式文字不等；跳到最新不补播；调节面板的落后上限与倍率生效
//   页面 页面上播放「短时间内大量事件堆积」与「标签页在后台放几分钟以后切回」两个场景
// 时间线本身的规则（不开浏览器）在 checks/timeline.js。
// 用法：node docs/prototypes/v13/checks/playback.js
const fs = require('fs');
const path = require('path');
const { chromium, EXE, v13Url } = require('./env');

const PIXEL = path.join(__dirname, '../js/pixel');

// 在页面里用确定的时钟驱动真正的画面：事件经真正的翻译层交给画面，就像页面上的那条路
const DRIVER = async () => {
  const Y = window.Y13;
  const P = Y.pixel;
  const T = Y.translate;
  const results = [];
  const check = (name, ok, detail) => results.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail) });

  let t = 0;
  const q = [];
  window.requestAnimationFrame = (cb) => { q.push(cb); return q.length; };
  window.cancelAnimationFrame = () => {};
  performance.now = () => t;
  let seed = 13579246;
  Math.random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const DT = 16;
  const step = (ms) => { for (let i = 0; i < Math.max(1, Math.round(ms / DT)); i++) { t += DT; const cbs = q.splice(0); for (const cb of cbs) cb(t); } };
  P.ecs.config.autonomy = false;

  const box = () => {
    const host = document.createElement('div');
    host.style.cssText = 'position:fixed;left:0;top:0;width:640px;height:320px;z-index:99999;background:#000';
    const canvas = document.createElement('canvas');
    host.appendChild(canvas);
    document.body.appendChild(host);
    return { host, canvas };
  };
  const role = (id, kind, name, status) => ({ id, kind, name, status: status || 'idle', task: null });
  const ROLES = {
    product: [role('p-mgr', 'manager', '产品部门经理'), role('p-arch', 'architect', '产品架构师', 'working'), role('p-exp', 'explorer', '产品探索者'), role('p-rev', 'reviewer', '产品审查者')],
    engineering: [role('e-mgr', 'manager', '工程经理'), role('e-arch', 'architect', '工程架构师', 'working'), role('e-lead', 'lead', '主程'), role('e-exp', 'explorer', '工程探索者'), role('e-rev', 'reviewer', '工程审查者')],
    quality: [role('q-mgr', 'manager', '质检经理'), role('q-test', 'tester', '测试工程师', 'working'), role('q-exp', 'explorer', '质检探索者'), role('q-rev', 'reviewer', '质检审查者')]
  };
  const allRoles = Object.values(ROLES).reduce((l, r) => l.concat(r), []);
  const names = { roleName: (id) => { const h = allRoles.find((r) => r.id === id || r.kind === id); return h ? h.name : null; } };
  const LOOP = (over) => Object.assign({
    items: [{ id: 'w1', title: '测试事项', color_index: 0, kind: 'request', status: 'running', department: 'engineering', cycle: 1, elapsed_sec: 100, limit_sec: 7200 }],
    open_requests: [], shelves: { adopted: [] }, slots: { total: 3, used: 1 }, waiting_provider: [], machines: null, ops: null, interrupted: false
  }, over || {});
  const roomModel = (department) => ({
    department, level: 'S5', status: 'working', crt: {}, roles: ROLES[department], pose: null, door: null, hold_card: null,
    mailbox: 0, summaries: 0, scrolls: 0, pinned_notes: 0, semantic_cards: 0, machine: null, remote_unknown: false,
    waiting_provider: false, pipes: null, existing_read: false, trial: null, tool_panel: null, self_test: null
  });

  // 堆积的事件：一百多条，三个部门，工具调用、模型请求、交接、询问、分派混着
  const LEADS = { product: 'p-arch', engineering: 'e-lead', quality: 'q-test' };
  const MGRS = { product: 'p-mgr', engineering: 'e-mgr', quality: 'q-mgr' };
  const DEPTS = ['product', 'engineering', 'quality'];
  function burstEvents(n) {
    const out = [];
    let ask = 0;
    for (let i = 0; i < n; i++) {
      const d = DEPTS[Math.floor(Math.random() * 3)];
      const base = { department: d, work_item_id: 'w1', project_id: 'p1', role: LEADS[d] };
      const k = Math.random();
      if (k < 0.3) out.push(Object.assign({ type: 'tool_started', tool: ['read_file', 'edit_range', 'bash', 'search'][Math.floor(Math.random() * 4)], label: d + '调用工具', payload: {} }, base));
      else if (k < 0.45) out.push(Object.assign({ type: 'model_requested', label: d + '思考', payload: {} }, base));
      else if (k < 0.52) out.push(Object.assign({ type: 'proposal_submitted', label: d + '提交', payload: {}, role: MGRS[d] }, base, { role: MGRS[d] }));
      else if (k < 0.6) out.push({ type: 'delivery_accepted', department: 'engineering', work_item_id: 'w1', project_id: 'p1', role: 'e-mgr', label: '交付被接纳', payload: {} });
      else if (k < 0.68) out.push({ type: 'spec_accepted', department: 'product', work_item_id: 'w1', project_id: 'p1', role: 'p-arch', label: 'PRD 被接纳', payload: {} });
      else if (k < 0.76) out.push({ type: 'qa_submitted', department: 'quality', work_item_id: 'w1', project_id: 'p1', role: 'q-test', label: '质检结论', payload: { verdict: Math.random() < 0.5 ? 'release' : 'rework_engineering' } });
      else if (k < 0.86) {
        const id = 'q' + (++ask);
        out.push({ type: 'ask_started', department: 'engineering', work_item_id: 'w1', project_id: 'p1', label: '工程询问产品：问题' + id, payload: { ask_id: id, requester: 'engineering', recipient: 'product', question: '问题' + id } });
        out.push({ type: 'ask_answered', department: 'product', work_item_id: 'w1', project_id: 'p1', label: '产品回答：答案' + id, payload: { ask_id: id, requester: 'engineering', recipient: 'product', answer: '答案' + id } });
      } else if (k < 0.93) out.push({ type: 'x_role_task_assigned', department: 'engineering', work_item_id: 'w1', project_id: 'p1', role: 'e-exp', label: '分派', payload: { to: 'e-exp', task: '查资料' } });
      else out.push({ type: 'x_role_result_returned', department: 'engineering', work_item_id: 'w1', project_id: 'p1', role: 'e-exp', label: '交回', payload: { to: 'e-exp' } });
    }
    return out;
  }

  // 场景的接口：楼层、房间、楼各一套「放状态、放事件」
  let pos = 0;
  const SCENES = {
    floor: () => {
      const b = box();
      const s = P.createFloorScene(b.canvas, {});
      const state = () => T.floor.state({ position: ++pos, loop: LOOP({ items: [Object.assign(LOOP().items[0], { elapsed_sec: pos })] }), roles: ROLES });
      s.jump(state());
      return { b, s, name: '楼层', state, event: (ev) => T.floor.actions(Object.assign({ position: ++pos }, ev), names).forEach((a) => s.play(a)) };
    },
    room: () => {
      const b = box();
      const s = P.createRoomScene(b.canvas, { department: 'engineering' });
      const state = () => T.room.state({ position: ++pos, workspace: { room: Object.assign(roomModel('engineering'), { summaries: pos }) } });
      s.jump(state());
      return { b, s, name: '房间', state, event: (ev) => T.room.actions(Object.assign({ position: ++pos }, ev), 'engineering', names).forEach((a) => s.play(a)) };
    },
    building: () => {
      const b = box();
      const s = P.createBuildingScene(b.canvas, {});
      const floors = [{ project_id: 'p1', name: 'P1', status: 'working', lit: {}, has_ops: false, flags: [], valve_closed: false, machine_ids: ['m1'], link_active: true, decisions: 0, runtime_machine: null }];
      const state = () => ({ position: ++pos, floors: floors.map((f, i) => Object.assign({}, f, { decisions: pos % 3 === 0 ? 1 : 0 })), show_basement: true });
      s.jump(state());
      return { b, s, name: '楼', state, event: (ev) => T.building.actions(Object.assign({ position: ++pos }, ev)).filter((a) => a.kind.indexOf('machine_') !== 0).forEach((a) => s.play(a)) };
    }
  };
  const drop = (m) => { m.s.destroy(); m.b.host.remove(); };

  // H8、H9：事件一条接一条到达，每条后面跟一份状态（就像页面按刷新清单重新查询）
  function burst(kind, settings, count, gapMs) {
    Object.assign(P.timeline.settings, { lagMs: 5000, minMs: 300, speed: 1 }, settings || {});
    const m = SCENES[kind]();
    step(300);
    let events = burstEvents(count);
    if (kind === 'building') {
      events = events.map((e, i) => Object.assign(e, { type: ['qa_submitted', 'ask_started', 'x_decision_issued', 'x_remote_action_started', 'x_deployed'][i % 5], payload: Object.assign({}, e.payload, { machine_id: 'm1', verdict: 'rework_engineering', ask_id: 'a' + i, requester: 'quality', recipient: 'engineering', decision_id: 'd' + i }) }));
    }
    let last = 0;
    events.forEach((ev) => {
      m.event(ev);
      m.s.setState(m.state());
      last = pos;
      step(gapMs);
    });
    let maxLag = 0;
    for (let i = 0; i < 4000; i++) { step(DT); const tl = m.s.inspect().timeline; if (tl.lag > maxLag) maxLag = tl.lag; if (!tl.pending && !tl.queued && !tl.playing.length) break; }
    const tl = m.s.inspect().timeline;
    const out = { name: m.name, tl, last, maxLag, lagMs: P.timeline.settings.lagMs };
    drop(m);
    return out;
  }

  try {
    // ------------------------------------------------------------------ H8、H9
    [['floor', 140], ['room', 140], ['building', 140]].forEach(([kind, n]) => {
      const r = burst(kind, null, n, 16);
      const st = r.tl.stats;
      check('H8 ' + r.name + '：堆积时落后不超过上限', st.maxLag <= r.lagMs + 2 * DT, '最大落后 ' + st.maxLag + ' 毫秒，上限 ' + r.lagMs);
      check('H9 ' + r.name + '：关键动作全部开始演，一个也不丢，正在演的不截断，限时的都在限定的时间内演完', st.droppedKey === 0 && st.startedKey === st.pushedKey && st.cutKey === 0 && st.late === 0, JSON.stringify(st));
      check(r.name + '：堆积以后最后显示的是最新的状态，时间线清空', r.tl.shown === r.last && !r.tl.pending && !r.tl.queued && !r.tl.playing.length, JSON.stringify({ shown: r.tl.shown, last: r.last, pending: r.tl.pending, queued: r.tl.queued }));
      if (kind !== 'building') check(r.name + '：堆积时普通动作被丢掉、关键动作被缩短或合并', st.dropped > 0 && (st.shortened > 0 || st.merged > 0), JSON.stringify(st));
    });
    // 调节面板：落后上限与倍率
    const tight = burst('floor', { lagMs: 2000 }, 140, 16);
    check('调节面板：落后上限调到 2 秒，H8 照样成立', tight.tl.stats.maxLag <= 2000 + 2 * DT, tight.tl.stats.maxLag);
    const slow = burst('floor', { speed: 2 }, 60, 16);
    check('调节面板：动作时长倍率 2，H8 与 H9 照样成立', slow.tl.stats.maxLag <= 5000 + 2 * DT && slow.tl.stats.droppedKey === 0 && slow.tl.stats.startedKey === slow.tl.stats.pushedKey && slow.tl.stats.cutKey === 0, JSON.stringify(slow.tl.stats));
    Object.assign(P.timeline.settings, { lagMs: 5000, minMs: 300, speed: 1 });
    {
      const m = SCENES.floor();
      step(300);
      P.timeline.settings.speed = 2;
      m.event({ type: 'delivery_accepted', department: 'engineering', work_item_id: 'w1', role: 'e-mgr', label: '交付', payload: {} });
      step(DT * 2);
      const playing = m.s.inspect().timeline.playing;
      const seal = playing.find((p) => p.kind === 'seal');
      check('调节面板：声明的时长乘以倍率（装箱封存 900 毫秒，倍率 2 时 1800）', seal && seal.ms === 1800, JSON.stringify(playing.map((p) => p.kind + ':' + p.ms)));
      P.timeline.settings.speed = 1;
      drop(m);
    }

    // ------------------------------------------------------------------ 状态等动作
    {
      const m = SCENES.floor();
      step(300);
      const before = m.s.inspect().timeline.shown;
      m.event({ type: 'delivery_accepted', department: 'engineering', work_item_id: 'w1', role: 'e-mgr', label: '交付', payload: {} });
      const stateAfter = m.state();
      m.s.setState(stateAfter);
      step(200);
      let tl = m.s.inspect().timeline;
      check('状态等动作：交付的动作还在演时新状态没有上画面', tl.shown === before && tl.pending === 1, JSON.stringify({ shown: tl.shown, before, pending: tl.pending }));
      step(9000);
      tl = m.s.inspect().timeline;
      check('状态等动作：动作演完以后新状态上画面', tl.shown === stateAfter.position && tl.pending === 0, JSON.stringify({ shown: tl.shown, want: stateAfter.position }));
      drop(m);
    }
    {
      const m = SCENES.floor();
      step(300);
      m.s.setState(m.state());
      step(DT * 3);
      const tl = m.s.inspect().timeline;
      check('状态等动作：没有要等的动作时下一帧就上画面', tl.pending === 0 && tl.shown === pos, JSON.stringify(tl));
      drop(m);
    }

    // ------------------------------------------------------------------ 实时内容不等
    {
      const m = SCENES.floor();
      step(300);
      for (let i = 0; i < 12; i++) m.event({ type: 'delivery_accepted', department: 'engineering', work_item_id: 'w1', role: 'e-mgr', label: '交付', payload: {} });
      step(200);
      const face = { id: 'dX', kind: 'waiting_resume', version: 1, title: '决定', work_item_id: 'w1', where: '项目', waited: '已等待 1 分', blocks: '不挡住事项', rows: [['部门', '工程']], links: [], options: [{ id: 'go', label: '继续', kind: 'primary' }], view: null };
      m.s.setDecisions([face]);
      const tl = m.s.inspect().timeline;
      check('实时内容：决定卡片在一串动作还在演时立刻在画面上', tl.playing.length + tl.queued > 0 && m.s.inspect().decisions.length === 1 && m.s.inspect().card.faces && true || m.s.inspect().decisions.length === 1, JSON.stringify({ playing: tl.playing.length, queued: tl.queued }));
      m.s.stream({ room: 'engineering', role: 'e-lead' }, '流式文字到了');
      const lead = m.s.inspect().world.characters['e-lead'];
      check('实时内容：流式文字在一串动作还在演时立刻出现在头顶', lead.progress && lead.progress.label.indexOf('流式文字到了') >= 0, lead.progress && lead.progress.label);
      drop(m);
    }

    // ------------------------------------------------------------------ 跳到最新
    {
      const m = SCENES.floor();
      step(300);
      burstEvents(160).forEach((ev) => { m.event(ev); m.s.setState(m.state()); step(8); });
      const piled = m.s.inspect().timeline;
      // 标签页在后台：浏览器暂停动画帧，事件照样到达（上面已经放进去了）；切回来：画面跳到最新
      const latest = m.state();
      m.s.jump(latest);
      step(DT * 3);
      const tl = m.s.inspect().timeline;
      check('跳到最新：切回以后直接显示最新的状态', tl.shown === latest.position && tl.pending === 0, JSON.stringify({ shown: tl.shown, want: latest.position }));
      check('跳到最新：积下的动作清空，不补播', tl.queued === 0 && tl.playing.length === 0 && piled.queued + piled.playing.length > 0, JSON.stringify({ piledQueued: piled.queued, piledPlaying: piled.playing.length, queued: tl.queued }));
      const ins = m.s.inspect();
      check('跳到最新：不留下沿管道走到一半的包裹', Object.keys(ins.world.packages).length === 0, Object.keys(ins.world.packages).length);
      step(3000);
      check('跳到最新：之后画面照常，没有补播的动作', m.s.inspect().timeline.stats.started === tl.stats.started, m.s.inspect().timeline.stats.started + ' / ' + tl.stats.started);
      drop(m);
    }
  } catch (e) {
    check('检查过程没有抛出错误', false, (e && e.stack) || e);
  }
  return results;
};

(async () => {
  const results = [];
  const check = (name, ok, detail) => results.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail) });
  const browser = await chromium.launch({ executablePath: EXE });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String((e && e.stack) || e).slice(0, 300)));
  await page.addInitScript(() => sessionStorage.setItem('y13.level', JSON.stringify('S5')));
  await page.goto(v13Url + '#/home');
  await page.waitForTimeout(900);

  // ---------------------------------------------------------------- H3 与覆盖（静态，加页面里的登记表）
  const info = await page.evaluate(() => ({
    events: Object.keys(window.Y13.registry.events),
    queries: Object.keys(window.Y13.registry.queries),
    coverage: window.Y13.translate.coverage
  }));
  const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/\s\/\/ .*$/gm, '');
  const files = fs.readdirSync(PIXEL).filter((f) => f.endsWith('.js'));
  const ALLOWED = new Set(['pixel', 'LEVELS']);
  files.forEach((f) => {
    const src = strip(fs.readFileSync(path.join(PIXEL, f), 'utf8'));
    const used = Array.from(new Set((src.match(/Y13\.[A-Za-z_]+/g) || []).map((x) => x.slice(4)))).filter((x) => !ALLOWED.has(x));
    check('H3 ' + f + '：只用 Y13.pixel 与档位 Y13.LEVELS，不导入 Yudao 的其他代码', used.length === 0, used.join(','));
    const kinds = info.events.filter((e) => new RegExp("['\"`]" + e + "['\"`]").test(src));
    check('H3 ' + f + '：不认 Yudao 的事件种类', kinds.length === 0, kinds.join(','));
    const queries = info.queries.filter((qn) => new RegExp("['\"`]" + qn.replace('.', '\\.') + "['\"`]").test(src));
    check('H3 ' + f + '：不认 Yudao 的查询名', queries.length === 0, queries.join(','));
  });

  ['floor', 'room', 'building'].forEach((scene) => {
    const c = info.coverage[scene];
    const name = { floor: '楼层', room: '房间', building: '楼' }[scene];
    const unmatched = info.events.filter((e) => !c.drawn.includes(e) && !c.realtime.includes(e) && !(e in c.none));
    check('翻译覆盖 ' + name + '：能力清单里的每种事件要么翻成动作，要么写明不画', unmatched.length === 0, unmatched.join(','));
    const noReason = Object.keys(c.none).filter((e) => !String(c.none[e]).trim());
    check('翻译覆盖 ' + name + '：每个「不画」都写了理由', noReason.length === 0, noReason.join(','));
    const both = Object.keys(c.none).filter((e) => c.drawn.includes(e) || c.realtime.includes(e));
    check('翻译覆盖 ' + name + '：同一种事件不同时翻成动作又列进不画', both.length === 0, both.join(','));
    const stale = Object.keys(c.none).concat(c.drawn, c.realtime).filter((e) => !info.events.includes(e));
    check('翻译覆盖 ' + name + '：对照表里没有登记表里不存在的事件种类', stale.length === 0, stale.join(','));
  });

  // ---------------------------------------------------------------- 确定的时钟下的场景
  const fresh = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  fresh.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  fresh.on('pageerror', (e) => errors.push(String((e && e.stack) || e).slice(0, 300)));
  await fresh.addInitScript(() => sessionStorage.setItem('y13.level', JSON.stringify('S5')));
  await fresh.goto(v13Url + '#/sys/machines');
  await fresh.waitForTimeout(900);
  (await fresh.evaluate(DRIVER)).forEach((r) => results.push(r));
  await fresh.close();

  // ---------------------------------------------------------------- 页面上的两个新场景（真实时钟）
  const play = async (id, tail, settings) => {
    const p = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    p.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    p.on('pageerror', (e) => errors.push(String((e && e.stack) || e).slice(0, 300)));
    await p.addInitScript(() => sessionStorage.setItem('y13.level', JSON.stringify('S5')));
    await p.goto(v13Url + '#/p/p-metro/overview');
    await p.waitForTimeout(1200);
    const r = await p.evaluate(async ({ sid, tail: wait, settings: set }) => {
      const Y = window.Y13;
      const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
      if (set) Object.assign(Y.pixel.timeline.settings, set);
      Y.scenario.select(sid);
      await sleep(600);
      const total = Y.scenario.current().steps.length;
      const trace = [];
      const fl = () => Y.scenes.activeFloor().floor;
      while (Y.scenario.state().step < total) {
        const step = Y.scenario.state().step;
        const sc = Y.scenario.current().steps[step];
        Y.scenario.step();
        await sleep(Math.min(sc.delay || 1200, 1500));
        const tl = fl().inspect().timeline;
        trace.push({ step: step + 1, lag: tl.lag, queued: tl.queued, playing: tl.playing.length, pending: tl.pending });
      }
      await sleep(wait);
      const tl = fl().inspect().timeline;
      const s = Y.pixel.timeline.settings;
      return { total, trace, tl, lagMs: s.lagMs, hidden: Boolean(Y.pixel.hidden) };
    }, { sid: id, tail, settings });
    await p.close();
    return r;
  };
  {
    // 极端的设置：落后上限 1 秒、最短时长 1 秒、倍率 3，到了上限时堆积的动作里有做它的角色被撤走的（事项完成以后角色表变了）
    const r = await play('sc-metro-burst', 40000, { lagMs: 1000, minMs: 1000, speed: 3 });
    const st = r.tl.stats;
    check('页面 场景 24 在极端设置下：到了上限强制上画面', st.forced > 0, JSON.stringify(st));
    check('页面 场景 24 在极端设置下：关键动作不截断，限时的都在限定的时间内演完，播完以后时间线清空', st.cutKey === 0 && st.late === 0 && st.droppedKey === 0 && !r.tl.pending && !r.tl.queued && !r.tl.playing.length, JSON.stringify(r.tl));
  }
  {
    const r = await play('sc-metro-burst', 14000);
    const st = r.tl.stats;
    check('页面 场景 24（短时间内大量事件堆积）：播完没有控制台错误', errors.length === 0, errors.slice(0, 2).join(' | '));
    check('页面 场景 24：画面落后不超过上限（H8）', st.maxLag <= r.lagMs + 150, st.maxLag + ' 毫秒，上限 ' + r.lagMs);
    check('页面 场景 24：关键动作不丢，正在演的不截断（H9）', st.droppedKey === 0 && st.startedKey === st.pushedKey && st.cutKey === 0 && st.late === 0, JSON.stringify(st));
    check('页面 场景 24：确实发生了堆积（普通动作被丢掉）', st.dropped > 0, JSON.stringify(st));
    check('页面 场景 24：播完以后时间线清空', !r.tl.pending && !r.tl.queued && !r.tl.playing.length, JSON.stringify(r.tl));
  }
  {
    const r = await play('sc-metro-background', 5000);
    check('页面 场景 25（标签页在后台放几分钟以后切回）：切回以后时间线清空，积下的动作没有补播', !r.tl.pending && !r.tl.queued && !r.tl.playing.length && !r.hidden, JSON.stringify({ tl: r.tl, hidden: r.hidden }));
    const during = r.trace.filter((x) => x.step >= 3 && x.step <= 17);
    check('页面 场景 25：后台那几分钟里事件到达，画面没有动（没有在演的动作）', during.every((x) => x.playing === 0), JSON.stringify(during.map((x) => x.playing)));
    check('页面 场景 25：切回前台时状态跳到最新（落后为零）', r.trace[r.trace.length - 1].lag === 0 && r.tl.stats.started < 20, JSON.stringify({ lag: r.trace[r.trace.length - 1].lag, started: r.tl.stats.started }));
  }
  check('检查过程没有控制台错误', errors.length === 0, errors.slice(0, 3).join(' | '));
  await browser.close();

  const bad = results.filter((x) => !x.ok);
  results.forEach((x) => console.log((x.ok ? 'PASS ' : 'FAIL ') + x.name + (x.ok ? '' : '  ← ' + x.detail)));
  console.log('共 ' + results.length + ' 项，失败 ' + bad.length + ' 项');
  console.log(bad.length ? 'RESULT: FAIL' : 'RESULT: PASS');
  process.exit(bad.length ? 1 : 0);
})();
