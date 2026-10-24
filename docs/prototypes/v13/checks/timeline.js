// 播放时间线的规则检查（画面与播放设计说明第 5.2 节、第 8 节 H8、H9）：在 Node 里直接加载 js/pixel/timeline.js，
// 用确定的时钟与一个只记录调用的渲染驱动它。不需要浏览器。
// 用法：node docs/prototypes/v13/checks/timeline.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '../js/pixel/timeline.js'), 'utf8');
const results = [];
const check = (name, ok, detail) => results.push({ name, ok: Boolean(ok), detail: detail === undefined ? '' : String(detail) });

function load() {
  const window = { Y13: { pixel: {} } };
  vm.runInNewContext(src, { window });
  return window.Y13.pixel.timeline;
}

// 一条时间线与它的渲染：natural(动作) 给出渲染自己演完需要多久（默认等于声明时长）
function rig(opts) {
  const T = load();
  Object.assign(T.settings, { lagMs: 5000, minMs: 300, speed: 1 }, (opts && opts.settings) || {});
  const DECL = Object.assign({
    handoff: { tier: 'key', ms: 2000 }, stamp: { tier: 'key', ms: 1000 }, read: { tier: 'normal', ms: 1200 },
    write: { tier: 'normal', ms: 1200 }, think: { tier: 'progress', ms: 0 }, flash: { tier: 'normal', ms: 700 }
  }, (opts && opts.decl) || {});
  let now = 0;
  const log = [];
  const live = new Map();
  const natural = (opts && opts.natural) || ((a, ms) => ms);
  const r = {
    T, log, applied: [], progress: [], cut: [], begun: [],
    get now() { return now; }
  };
  const tl = T.create({
    clock: () => now,
    classify: (a) => Object.assign({ lanes: a.lanes || [] }, DECL[a.kind]),
    begin(e) { r.begun.push({ at: now, kind: e.action.kind, pos: e.pos, ms: e.ms, lanes: e.lanes.slice(), tier: e.tier }); live.set(e.id, now + natural(e.action, e.ms)); },
    cut(e) { r.cut.push({ at: now, kind: e.action.kind, pos: e.pos }); live.delete(e.id); },
    apply(s) { r.applied.push({ at: now, pos: s.position }); },
    progress(a) { r.progress.push({ at: now, kind: a.kind }); }
  });
  r.tl = tl;
  // 推进时钟：每帧 dt 毫秒，先把到时间的渲染报告演完，再推进时间线
  r.run = (ms, dt) => {
    const step = dt || 16;
    const until = now + ms;
    while (now < until) {
      now = Math.min(until, now + step);
      live.forEach((at, id) => { if (now >= at) { tl.done(id); live.delete(id); } });
      tl.tick();
    }
  };
  let pos = 0;
  r.act = (kind, lanes, extra) => { pos += 1; tl.push(Object.assign({ kind, position: pos, lanes }, extra || {})); return pos; };
  r.state = (p) => tl.state({ position: p === undefined ? pos : p });
  r.jump = () => tl.jump({ position: pos });
  r.pos = () => pos;
  return r;
}

// 1. 排队：同一个参与方依次演，不同参与方同时演；动作至少演满声明的时长
{
  const r = rig();
  r.jump();
  r.act('read', ['e']); r.act('write', ['e']); r.act('read', ['q']);
  r.run(16);
  check('排队：不同参与方的动作同一帧开始', r.begun.length === 2 && r.begun.every((b) => b.at === 16), JSON.stringify(r.begun));
  r.run(1200);
  const w = r.begun.find((b) => b.kind === 'write');
  check('排队：同一个参与方的下一件事等上一件演完', w && w.at >= 1216, w && w.at);
}

// 2. 状态等它之前的动作演完；位置更大的动作不挡它；没有动作要等时下一帧就上画面
{
  const r = rig();
  r.jump();
  r.act('handoff', ['e', 'q']);
  const p2 = r.act('stamp', ['q']);
  r.state(p2);
  r.act('read', ['e']);
  r.state();
  r.run(16);
  check('状态：前面的动作还在演时不上画面', r.applied.length === 1, JSON.stringify(r.applied));
  r.run(3100);
  const a2 = r.applied.find((x) => x.pos === p2);
  check('状态：位置不大于它的动作全部演完以后上画面', a2 && a2.at >= 3000, JSON.stringify(r.applied));
  r.run(2000);
  check('状态：最后一份在它前面的动作演完以后上画面', r.applied[r.applied.length - 1].pos === r.pos(), JSON.stringify(r.applied));
  const r2 = rig();
  r2.jump();
  r2.state();
  r2.run(16);
  check('状态：没有要等的动作时下一帧上画面', r2.applied.length === 2 && r2.applied[1].at === 16, JSON.stringify(r2.applied));
}

// 3. 演满声明的时长与等渲染演完
{
  const r = rig({ natural: (a, ms) => (a.slow ? ms + 900 : 100) });
  r.jump();
  r.act('read', ['e']); r.act('write', ['e']);
  r.act('read', ['q'], { slow: true }); r.act('write', ['q']);
  r.run(3000);
  const w = r.begun.filter((b) => b.kind === 'write');
  check('时长：渲染提前演完，也要演满声明的时长', w.find((b) => b.lanes[0] === 'e').at >= 1200, w[0] && w[0].at);
  check('时长：渲染演得比声明长，等它演完', w.find((b) => b.lanes[0] === 'q').at >= 2100, w[1] && w[1].at);
  check('时长：平常没有被截断的动作', r.cut.length === 0, JSON.stringify(r.cut));
}

// 4. 队伍过长：一个参与方排着的普通动作最多三条，丢掉最早的
{
  const r = rig();
  r.jump();
  r.act('handoff', ['e']);
  for (let i = 0; i < 6; i++) r.act('read', ['e']);
  const ins = r.tl.inspect();
  check('队伍过长：排着的普通动作留三条（加上排着的一条关键动作）', ins.queued === 4, ins.queued);
  check('队伍过长：丢掉的是最早的三条普通动作', ins.stats.dropped === 3 && ins.stats.droppedKey === 0, JSON.stringify(ins.stats));
}

// 5. 进度：不排队，到了就交给渲染，状态不等它
{
  const r = rig();
  r.jump();
  r.act('read', ['e']);
  r.act('think', ['e']);
  r.state();
  r.run(16);
  check('进度：到了立刻交给渲染', r.progress.length === 1 && r.progress[0].at === 0, JSON.stringify(r.progress));
  r.run(1300);
  check('进度：状态只等普通动作，不等进度', r.applied.length === 2 && r.applied[1].at <= 1300, JSON.stringify(r.applied));
}

// 6. 堆积（H8、H9）：两秒里到达 120 条动作，三个参与方，关键与普通混着，每条事件后面跟一份状态。
// overrun 为渲染演得比声明时长更久的概率（走路、包裹在管道里走这类时间不在声明里）
function burst(seed, settings, frame, overrun, count) {
  const r = rig({ settings, natural: (a, ms) => ms + (a.extra || 0) });
  let s = seed;
  const rnd = () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; };
  r.jump();
  const lanes = [['p'], ['e'], ['q'], ['e', 'q'], ['p', 'e']];
  for (let i = 0; i < (count || 120); i++) {
    const k = rnd();
    const kind = k < 0.25 ? 'handoff' : k < 0.4 ? 'stamp' : k < 0.7 ? 'read' : k < 0.85 ? 'write' : 'think';
    const ln = kind === 'handoff' ? lanes[3 + Math.floor(rnd() * 2)] : lanes[Math.floor(rnd() * 3)];
    r.act(kind, ln, { extra: rnd() < overrun ? 1500 : 0 });
    r.state();
    r.run(16, frame);
  }
  r.run(60000, frame);
  return r;
}
[[1, null, 16, 0], [7, null, 50, 0], [42, { lagMs: 2000 }, 16, 0], [99, { lagMs: 8000, speed: 2 }, 33, 0],
  [3, null, 16, 0.3], [5, { lagMs: 3000 }, 50, 0.5]].forEach(([seed, settings, frame, overrun]) => {
  const r = burst(seed, settings, frame, overrun);
  const st = r.tl.inspect().stats;
  const lagMs = (settings && settings.lagMs) || 5000;
  const tag = '（种子 ' + seed + '，上限 ' + lagMs + '，每帧 ' + frame + ' 毫秒' + (overrun ? '，渲染常常超时' : '') + '）';
  check('H8 落后有上限' + tag, st.maxLag <= lagMs + frame, '最大落后 ' + st.maxLag + ' 毫秒');
  check('H9 关键动作不丢' + tag, st.droppedKey === 0 && st.startedKey === st.pushedKey, JSON.stringify(st));
  check('堆积：普通动作被丢掉，关键动作被缩短或合并' + tag, st.dropped > 0 && (st.shortened > 0 || st.merged > 0), JSON.stringify(st));
  check('堆积：缩短的关键动作不短于最短时长' + tag, r.begun.filter((b) => b.tier === 'key').every((b) => b.ms >= T_MIN(settings)), r.begun.filter((b) => b.ms < T_MIN(settings)).length);
  check('堆积：最后显示的是最新的状态' + tag, r.applied[r.applied.length - 1].pos === r.pos(), r.applied[r.applied.length - 1].pos + ' / ' + r.pos());
});
function T_MIN(settings) { return (settings && settings.minMs) || 300; }

// 6b. 缩到最短时长还放得下的堆积（一秒半里 40 条）：快进赶在上限之前，不用强制，也没有截断正在演的关键动作
[11, 23, 57].forEach((seed) => {
  const r = burst(seed, null, 16, 0, 40);
  const st = r.tl.inspect().stats;
  const tag = '（种子 ' + seed + '）';
  check('放得下的堆积：快进赶在上限之前，不用强制' + tag, st.forced === 0, JSON.stringify(st));
  check('放得下的堆积：H8 与 H9' + tag, st.maxLag <= 5016 && st.droppedKey === 0 && st.startedKey === st.pushedKey, JSON.stringify(st));
});

// 7. 极端堆积：一个参与方一下子到达 40 条不同种类交替的关键动作，缩到最短也演不完：状态照样在上限之内上画面，关键动作接着演完
{
  const r = rig();
  r.jump();
  for (let i = 0; i < 40; i++) r.act(i % 2 ? 'stamp' : 'handoff', ['e']);
  r.state();
  r.run(5200);
  const st = r.tl.inspect().stats;
  check('极端堆积：到了上限，状态照样上画面', r.applied.length === 2 && r.applied[1].at <= 5016, JSON.stringify(r.applied));
  check('极端堆积：到了上限算一次强制', st.forced === 1, st.forced);
  r.run(30000);
  const st2 = r.tl.inspect().stats;
  check('极端堆积：排着的关键动作全部演完', st2.startedKey === 40 && st2.droppedKey === 0, JSON.stringify(st2));
}

// 8. 合并：同一个参与方连续的同类关键动作在来不及时合并成一次
{
  const r = rig();
  r.jump();
  for (let i = 0; i < 12; i++) r.act('stamp', ['q']);
  r.state();
  r.run(8000);
  const st = r.tl.inspect().stats;
  check('合并：连续的同类关键动作合并', st.merged > 0 && r.begun.length < 12, JSON.stringify(st) + ' 开始 ' + r.begun.length);
  check('合并：合并的动作算作开始演了', st.startedKey === 12, st.startedKey);
  check('合并：状态在上限之内上画面', st.maxLag <= 5016, st.maxLag);
}

// 9. 跳到最新：正在演的立刻结束，排着的清掉，直接显示给出的状态，不补播
{
  const r = rig();
  r.jump();
  r.act('handoff', ['e']); r.act('read', ['e']); r.act('stamp', ['q']);
  r.state();
  r.run(100);
  const before = r.begun.length;
  r.jump();
  r.run(5000);
  check('跳到最新：正在演的动作立刻结束', r.cut.length === 2, JSON.stringify(r.cut));
  check('跳到最新：排着的动作不再演', r.begun.length === before, r.begun.length + ' / ' + before);
  check('跳到最新：直接显示给出的状态', r.applied[r.applied.length - 1].pos === r.pos() && r.applied[r.applied.length - 1].at === 100, JSON.stringify(r.applied));
}

// 10. 标签页在后台：时钟不走（浏览器暂停动画），事件照样到达；切回来跳到最新，积下的动作不补播
{
  const r = rig();
  r.jump();
  for (let i = 0; i < 200; i++) { r.act(i % 3 ? 'read' : 'handoff', [['p'], ['e'], ['q']][i % 3]); r.state(); }
  const piled = r.tl.inspect();
  r.jump();
  r.run(1000);
  const ins = r.tl.inspect();
  check('后台切回：积下的状态没有逐份补上', r.applied.length === 2, r.applied.length);
  check('后台切回：积下的动作不补播', r.begun.length === 0 && ins.queued === 0, r.begun.length + ' ' + ins.queued + '（切回前排着 ' + piled.queued + ' 条）');
}

// 11. 旧的状态：比画面上的状态还旧的查询结果不上画面
{
  const r = rig();
  r.act('read', ['e']);
  r.jump();
  r.tl.state({ position: 0 });
  r.run(100);
  check('旧的状态：比画面上的还旧时不上画面', r.applied.length === 1, JSON.stringify(r.applied));
}

// 12. 倍率：声明的时长乘以倍率
{
  const r = rig({ settings: { speed: 0.5 } });
  r.jump();
  r.act('handoff', ['e']);
  r.run(16);
  check('倍率：声明时长乘以倍率', r.begun[0].ms === 1000, r.begun[0].ms);
}

const bad = results.filter((x) => !x.ok);
results.forEach((x) => console.log((x.ok ? 'PASS ' : 'FAIL ') + x.name + (x.ok ? '' : ' — ' + x.detail)));
console.log(JSON.stringify({ checks: results.length, failed: bad.length }));
console.log(bad.length ? 'RESULT: FAIL' : 'RESULT: PASS');
process.exit(bad.length ? 1 : 0);
