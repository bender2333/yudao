// 回放比较：把 record.js 在 v12 上录下的楼层画面调用，按确定的时钟回放给 v12 与 v13 的项目楼层画面，截取检查点。
// 时钟、随机数与小人的动画计时都固定。v13 的画面只认画面合同：录到的 floorModel 与事件经过真正的翻译层（js/translate/）再交给它。
//
// 两类检查点：
// - 每段录制的最后一个（事件播完，静置 14 秒，时间线放空）：整张 canvas 逐像素、逐个小人（位置、姿势、图标……）与 v12 比较，事实层不应该变。
// - 中间的（每个事件之后：事件刚演的时候、静置以后）：v12 没有播放时间线，演的时间不同，不与 v12 比较，与 v13 自己的基线比较。
//   基线存在 .tmp/v13-checks/replay-golden/，改动画面或播放规则、看过差异图确认以后用 --rebaseline 重新生成。
//   中间检查点里静置以后的，与 v12 相同的个数只统计，不判定。
//
// 用法：node docs/prototypes/v13/checks/replay.js [--v13 <index.html 的 file:// 地址>] [--only 场景编号,场景编号] [--mode step|burst]
//   [--recs 录制文件名] [--rebaseline] [--keep 4] [--reduced] [--free-anim]
// 先运行 record.js 生成 .tmp/v13-checks/recordings.json；有差异的检查点会把两边的画面与差异图存进 .tmp/v13-checks/replay/。
// step：每个事件之后截取；burst：事件连续播放，只在最后截取；--reduced：系统设置为减少动画；
// --free-anim：不固定小人的动画计时，用来看差异是否只来自动画相位（小人状态里的 phase 字段）。
const fs = require('fs');
const path = require('path');
const { chromium, EXE, v12Url, v13Url, outDir, spaceOf } = require('./env');

const arg = (name, dflt) => { const i = process.argv.indexOf('--' + name); return i >= 0 ? process.argv[i + 1] : dflt; };
const V12 = v12Url;
const V13 = arg('v13', v13Url);
const ONLY = arg('only', '') ? arg('only').split(',') : null;
const MODE = arg('mode', 'step');
const KEEP = Number(arg('keep', 4));
const REDUCED = process.argv.includes('--reduced');
const REBASE = process.argv.includes('--rebaseline');
const FREE = process.argv.includes('--free-anim');
if (REBASE && FREE) throw new Error('--rebaseline 与 --free-anim 不能一起用');
const OUT = path.join(outDir, 'replay');
const GOLDEN = path.join(outDir, 'replay-golden');
fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(GOLDEN, { recursive: true });

const recordings = JSON.parse(fs.readFileSync(path.join(outDir, arg('recs', 'recordings.json')), 'utf8'))
  .filter((r) => !ONLY || ONLY.includes(r.id));

// 在页面里运行的回放驱动
const DRIVER = async ({ ops, mode, DT, SETTLE, GAP_EVENT, GAP_OTHER, space, freeAnim }) => {
  const P = window[space].pixel;
  window.__freeAnim = freeAnim;
  // 确定的时钟与随机数
  let t = 0;
  const q = [];
  window.requestAnimationFrame = (cb) => { q.push(cb); return q.length; };
  window.cancelAnimationFrame = () => {};
  performance.now = () => t;
  let seed = 987654321;
  Math.random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const step = (ms) => {
    const n = Math.max(1, Math.round(ms / DT));
    for (let i = 0; i < n; i++) {
      t += DT;
      const cbs = q.splice(0);
      for (const cb of cbs) cb(t);
    }
  };

  // 统计画面对 ecs.js 的使用
  const counts = {};
  const E = P.ecs;
  // 自主行为（待机活动、管道的惯性）关掉：静止的画面只由快照决定，才能与 v12 逐像素比较
  if (E && E.config) E.config.autonomy = false;
  if (E) {
    ['dispatch', 'declareRooms', 'declareLinks', 'syncCharacters', 'stepCharacters', 'spawnPackage', 'sendPackage', 'stepPackages', 'stepPipes', 'bubbleFor'].forEach((k) => {
      if (typeof E[k] !== 'function') return;
      const orig = E[k];
      E[k] = function () { counts[k] = (counts[k] || 0) + 1; return orig.apply(this, arguments); };
    });
  }

  const host = document.createElement('div');
  host.style.cssText = 'position:fixed;left:0;top:0;width:640px;height:320px;z-index:99999;background:#000';
  const canvas = document.createElement('canvas');
  host.appendChild(canvas);
  document.body.appendChild(host);

  const clone = (v) => JSON.parse(JSON.stringify(v));
  // 全部角色实体（S5 的角色也算）：动画时钟固定，位置与姿势逐个比较
  const isWorker = (a) => Boolean(a.data && a.data.ecsChar);

  // v13 的画面只认画面合同：录到的 floorModel 与事件（v12 的说法）经过真正的翻译层再交给它。
  // 录制里的 transition 与 collaboration_* 是 v12 的界面层从成果事件与询问事件派生出来的，翻译层自己会翻出交接与传信，这里不重复放
  const adapt = (f) => {
    const T = window[space].translate;
    const Y = window[space];
    let pos = 0;
    let roles = [];
    let firstState = true;
    const names = { roleName: (id) => { const h = roles.find((r) => r.id === id || r.kind === id); return h ? h.name : null; } };
    f.setModel = (model) => {
      roles = Object.values(model.roles || {}).reduce((l, r) => l.concat(r), []);
      const s = T.floor.state({ position: ++pos, loop: model, roles: model.roles, focus: model.focus_id });
      if (firstState) { f.jump(s); firstState = false; } else f.setState(s);
      f.setDecisions(model.decisions || []);
    };
    // 询问与回答在 v12 里是页面派生的 collaboration_requested、collaboration_responded，v13 的翻译层认原始事件 ask_started、ask_answered，载荷相同
    const RAW = { collaboration_requested: 'ask_started', collaboration_responded: 'ask_answered' };
    f.playEvent = (ev) => {
      if (ev.type === 'transition' || ev.type === 'collaboration_closed') return;
      const raw = RAW[ev.type] ? Object.assign({}, ev, { type: RAW[ev.type] }) : ev;
      const s = T.stream(raw);
      if (s) f.stream(s.who, s.text);
      T.floor.actions(Object.assign({ position: ++pos }, raw), names).forEach((a) => f.play(a));
    };
    const setOverlay = f.setOverlay;
    // 覆盖层的取值在录制里是 v12 页面拼好的形状，这里换成合同里的形状
    f.setOverlay = (id, data) => {
      if (!data) return setOverlay(id, null);
      const src = () => 'rule';
      let out;
      if (id === 'flow') out = { segments: data.segments.map((s) => ({ from: s.from, to: s.to, kind: s.kind, count: s.count, last_text: Y.time.clock(s.last_at) })) };
      else if (id === 'waiting') out = { entries: data.entries.map((e) => ({ department: e.department, text: e.text, waited_text: Y.time.duration(e.waited_sec), row: e.row })) };
      else if (id === 'loops' || id === 'coverage') out = T.floor.overlay(id, data, src);
      else out = data;
      return setOverlay(id, out);
    };
    return f;
  };
  let fl = null;
  const cps = [];
  let failure = null;

  // kind：play（事件刚演的时候）、settled（静置以后，时间线放空）、end（这段录制的最后一个）
  function shoot(label, kind) {
    const sc = fl.scene;
    const workers = sc.actors.filter(isWorker).sort((a, b) => (a.sprite < b.sprite ? -1 : 1));
    const state = workers.map((a) => ({
      sprite: a.sprite, x: Math.round(a.x * 100) / 100, y: Math.round(a.y * 100) / 100, seat: Boolean(a.seat), anim: a.anim,
      facing: a.facing, icon: a.icon ? { kind: a.icon.kind, text: a.icon.text || null } : null,
      visible: a.visible, dim: a.dim, hold: a.hold || null, sign: a.sign || null, script: Boolean(a.script),
      phase: window.__freeAnim ? Math.round(a.clock - a.animStart) : null, clock: window.__freeAnim ? Math.round(a.clock) : null
    }));
    // 固定动画相位：小人的动画计时与场景的动画时钟在两版里取同一个值
    if (!window.__freeAnim) workers.forEach((a, i) => { a.clock = 5000; a.animStart = 0; a.seed = 100 + i; });
    sc.animT = 20000;
    sc.drawNow();
    cps.push({ label, kind, state, png: canvas.toDataURL('image/png'), t, frozen: Boolean(sc.frozen) });
  }

  try {
    let sinceCheckpoint = 0;
    let first = true;
    for (let i = 0; i < ops.length; i++) {
      const o = ops[i];
      if (o.op === 'mount') { fl = P.createFloorScene(canvas, { onDoorClick() {} }); if (space === 'Y13') fl = adapt(fl); first = true; continue; }
      if (!fl) continue;
      if (o.op === 'destroy') { fl.destroy(); fl = null; continue; }
      if (o.op === 'setModel') fl.setModel(clone(o.arg));
      else if (o.op === 'focus') fl.focus(o.arg);
      else if (o.op === 'setOverlay') fl.setOverlay(o.arg.id, o.arg.data);
      else if (o.op === 'playEvent') { fl.playEvent(clone(o.arg)); sinceCheckpoint++; }
      step(o.op === 'playEvent' ? GAP_EVENT : GAP_OTHER);
      const nextOp = ops[i + 1] && ops[i + 1].op;
      const endOfRefresh = o.op === 'setOverlay' && nextOp !== 'focus';
      if (endOfRefresh && first) { step(SETTLE); shoot('初始 #' + i, 'settled'); first = false; sinceCheckpoint = 0; }
      else if (endOfRefresh && mode === 'step' && sinceCheckpoint > 0) {
        const lastEv = [...ops.slice(0, i + 1)].reverse().find((x) => x.op === 'playEvent');
        const type = lastEv ? lastEv.arg.type : '?';
        shoot('播放中 ' + type + ' #' + i, 'play');
        step(SETTLE);
        shoot('事件 ' + type + ' #' + i, 'settled');
        sinceCheckpoint = 0;
      }
    }
    if (fl) { step(SETTLE); shoot('结束', 'end'); }
  } catch (e) {
    failure = String((e && e.stack) || e).slice(0, 600);
  }
  return { cps, counts, failure };
};

async function version(browser, root, rec) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: REDUCED ? 'reduce' : 'no-preference' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  const { ns, prefix } = spaceOf(root);
  await page.addInitScript(([key, lv]) => sessionStorage.setItem(key, JSON.stringify(lv)), [prefix + '.level', 'S5']);
  await page.goto(root + '#/sys/machines');
  await page.waitForTimeout(700);
  const res = await page.evaluate(DRIVER, {
    ops: rec.ops, mode: MODE, DT: 50, SETTLE: 14000, GAP_EVENT: 900, GAP_OTHER: 50, space: ns, freeAnim: FREE
  });
  await ctx.close();
  return Object.assign(res, { errors });
}

// rects：不参与比较的矩形 [x0, y0, x1, y1]（整层中断时小人停在哪里取决于中断之前的动作，只比较小人以外的画面）
async function diff(cmp, a, b, rects) {
  if (a === b) return { count: 0 };
  return cmp.evaluate(async ([x, y, masks]) => {
    const load = (src) => new Promise((res) => { const im = new Image(); im.onload = () => res(im); im.src = src; });
    const [ia, ib] = await Promise.all([load(x), load(y)]);
    if (ia.width !== ib.width || ia.height !== ib.height) return { count: -1, size: [ia.width, ia.height, ib.width, ib.height] };
    const cv = document.createElement('canvas');
    cv.width = ia.width; cv.height = ia.height;
    const cx = cv.getContext('2d');
    cx.drawImage(ia, 0, 0);
    const da = cx.getImageData(0, 0, cv.width, cv.height).data;
    cx.clearRect(0, 0, cv.width, cv.height);
    cx.drawImage(ib, 0, 0);
    const imgB = cx.getImageData(0, 0, cv.width, cv.height);
    const db = imgB.data;
    let count = 0, x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
    const out = cx.createImageData(cv.width, cv.height);
    for (let i = 0; i < da.length; i += 4) {
      const p = i / 4, px = p % cv.width, py = (p - px) / cv.width;
      const masked = masks && masks.some((m) => px >= m[0] && px <= m[2] && py >= m[1] && py <= m[3]);
      const same = masked || (da[i] === db[i] && da[i + 1] === db[i + 1] && da[i + 2] === db[i + 2]);
      if (same) {
        out.data[i] = db[i] * 0.35; out.data[i + 1] = db[i + 1] * 0.35; out.data[i + 2] = db[i + 2] * 0.35; out.data[i + 3] = 255;
      } else {
        count++;
        x0 = Math.min(x0, px); y0 = Math.min(y0, py); x1 = Math.max(x1, px); y1 = Math.max(y1, py);
        out.data[i] = 255; out.data[i + 1] = 40; out.data[i + 2] = 40; out.data[i + 3] = 255;
      }
    }
    cx.putImageData(out, 0, 0);
    return { count, bbox: [x0, y0, x1, y1], png: cv.toDataURL('image/png') };
  }, [a, b, rects || null]);
}

const save = (name, dataUrl) => fs.writeFileSync(path.join(OUT, name), Buffer.from(dataUrl.split(',')[1], 'base64'));

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const cmp = await browser.newPage();
  await cmp.goto('about:blank');
  const summary = [];
  // 比较两个检查点：像素（整层中断时小人停在中断前的位置，只比较小人以外的部分）与小人的状态（逐个小人逐个字段）
  async function compare(A, B) {
    const frozen = A.frozen || B.frozen;
    const boxes = frozen ? A.state.concat(B.state).map((s) => [Math.round(s.x) - 40, Math.round(s.y) - 72, Math.round(s.x) + 40, Math.round(s.y) + 8]) : null;
    const d = await diff(cmp, A.png, B.png, boxes);
    const fields = [];
    const keys = new Set();
    if (!frozen) {
      A.state.forEach((s, k) => {
        const u = B.state[k] || {};
        Object.keys(s).forEach((key) => { if (JSON.stringify(s[key]) !== JSON.stringify(u[key])) { keys.add(key); fields.push(s.sprite + '.' + key + ' ' + JSON.stringify(s[key]) + ' → ' + JSON.stringify(u[key])); } });
      });
      if (A.state.length !== B.state.length) { keys.add('小人数量'); fields.push('小人数量 ' + A.state.length + ' → ' + B.state.length); }
    }
    return { frozen, d, fields, keys };
  }
  // 与 v12 有差异的检查点：哪些小人字段不同的次数，以及只有像素不同、小人字段全部相同的个数
  const tallyV12 = (row, r) => {
    if (!r.fields.length && r.d.count === 0) return;
    row.v12Diff = row.v12Diff || { checkpoints: 0, pixelOnly: 0, keys: {} };
    row.v12Diff.checkpoints++;
    if (!r.fields.length) row.v12Diff.pixelOnly++;
    r.keys.forEach((k) => { row.v12Diff.keys[k] = (row.v12Diff.keys[k] || 0) + 1; });
  };
  let kept = 0;
  async function runOne(rec) {
    const a = await version(browser, V12, rec);
    const b = await version(browser, V13, rec);
    const row = { id: rec.id, checkpoints: b.cps.length, endPixel: 0, endState: 0, goldPixel: 0, goldState: 0, settledSameAsV12: 0, settled: 0,
      v12fail: a.failure, v13fail: b.failure, v12errors: a.errors.length, v13errors: b.errors.length, ecs: b.counts, notes: [] };
    const note = (s) => { if (row.notes.length < 8) row.notes.push(s); };
    const keep = (tag, X, Y, d, nameX, nameY) => {
      if (kept >= KEEP || !d.png) return;
      kept++;
      save(tag + '-' + nameX + '.png', X.png); save(tag + '-' + nameY + '.png', Y.png); save(tag + '-diff.png', d.png);
    };
    if (a.cps.length !== b.cps.length) { row.endState++; note('检查点数量不同 ' + a.cps.length + ' / ' + b.cps.length); return row; }
    const ends = a.cps.map((c, i) => i).filter((i) => a.cps[i].kind === 'end');
    if (ends.length !== 1 || ends[0] !== a.cps.length - 1) { row.endState++; note('没有取到这段录制的最后一个检查点'); return row; }
    // 1. 最后一个检查点：对 v12
    {
      const i = ends[0];
      const r = await compare(a.cps[i], b.cps[i]);
      if (r.frozen) row.frozenEnd = true;
      tallyV12(row, r);
      if (r.fields.length) { row.endState++; note('[结束 小人] ' + r.fields.join('；')); }
      if (r.d.count !== 0) {
        row.endPixel++;
        note('[结束 像素] 差异 ' + r.d.count + ' 个像素 ' + (r.d.bbox ? JSON.stringify(r.d.bbox) : JSON.stringify(r.d.size)));
        keep(rec.id + '-end', a.cps[i], b.cps[i], r.d, 'v12', 'v13');
      }
    }
    // 2. 中间的检查点：对 v13 自己的基线；静置以后的另外统计与 v12 是否相同
    const mids = b.cps.filter((c) => c.kind !== 'end');
    const goldPath = path.join(GOLDEN, rec.id + '.json');
    if (FREE) {
      // 不固定动画计时时只统计与 v12 的差异，不比较基线
    } else if (REBASE) {
      if (row.endPixel || row.endState) { note('最后一个检查点与 v12 有差异，不更新基线'); return row; }
      fs.writeFileSync(goldPath, JSON.stringify(mids.map(({ label, kind, state, png, frozen }) => ({ label, kind, state, png, frozen }))));
      row.rebaselined = mids.length;
    } else {
      if (!fs.existsSync(goldPath)) throw new Error('没有基线 ' + goldPath + '，先运行 --rebaseline');
      const gold = JSON.parse(fs.readFileSync(goldPath, 'utf8'));
      if (gold.length !== mids.length || gold.some((g, i) => g.label !== mids[i].label)) { row.goldState++; note('中间检查点与基线的数量或标签不同 ' + mids.length + ' / ' + gold.length); }
      else {
        for (let i = 0; i < mids.length; i++) {
          const r = await compare(gold[i], mids[i]);
          if (r.fields.length) { row.goldState++; note('[基线 小人] ' + mids[i].label + ' ' + r.fields.join('；')); }
          if (r.d.count !== 0) {
            row.goldPixel++;
            note('[基线 像素] ' + mids[i].label + ' 差异 ' + r.d.count + ' 个像素 ' + (r.d.bbox ? JSON.stringify(r.d.bbox) : JSON.stringify(r.d.size)));
            keep(rec.id + '-' + String(i).padStart(2, '0'), gold[i], mids[i], r.d, 'baseline', 'now');
          }
        }
      }
    }
    // 静置以后的中间检查点与 v12 相同的个数（a.cps 与 b.cps 的检查点一一对应）
    for (let i = 0; i < b.cps.length; i++) {
      if (b.cps[i].kind !== 'settled') continue;
      row.settled++;
      const r = await compare(a.cps[i], b.cps[i]);
      tallyV12(row, r);
      if (!r.fields.length && r.d.count === 0) row.settledSameAsV12++;
      else if (r.fields.length) { if (FREE) note('[静置 小人] ' + b.cps[i].label + ' ' + r.fields.slice(0, 3).join('；')); }
      // 小人的字段都相同，只有像素不同：要看差异图
      else { note('[静置 只有像素不同] ' + b.cps[i].label + ' 差异 ' + r.d.count + ' 个像素 ' + (r.d.bbox ? JSON.stringify(r.d.bbox) : JSON.stringify(r.d.size))); keep(rec.id + '-settled-' + String(i).padStart(2, '0'), a.cps[i], b.cps[i], r.d, 'v12', 'v13'); }
    }
    return row;
  }
  for (const rec of recordings) {
    const row = await runOne(rec);
    summary.push(row);
    console.log(JSON.stringify(row));
  }
  await browser.close();
  const sum = (k) => summary.reduce((s, r) => s + (r[k] || 0), 0);
  const bad = summary.filter((r) => r.endPixel || r.endState || r.goldPixel || r.goldState || r.v12fail || r.v13fail || r.v12errors || r.v13errors);
  console.log(JSON.stringify({ recordings: summary.length, checkpoints: sum('checkpoints'), badRecordings: bad.length, endPixel: sum('endPixel'), endState: sum('endState'),
    goldPixel: sum('goldPixel'), goldState: sum('goldState'), settled: sum('settled'), settledSameAsV12: sum('settledSameAsV12'), rebaselined: sum('rebaselined'),
    v12Diff: summary.reduce((m, r) => {
      if (!r.v12Diff) return m;
      m.checkpoints += r.v12Diff.checkpoints; m.pixelOnly += r.v12Diff.pixelOnly;
      Object.keys(r.v12Diff.keys).forEach((k) => { m.keys[k] = (m.keys[k] || 0) + r.v12Diff.keys[k]; });
      return m;
    }, { checkpoints: 0, pixelOnly: 0, keys: {} }) }));
  console.log(bad.length ? 'RESULT: DIFF' : 'RESULT: PASS');
  process.exit(bad.length ? 1 : 0);
})();
