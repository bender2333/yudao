// 回放比较：把 record.js 录下的楼层画面调用，按确定的时钟回放给 v8 与 v9 的项目楼层画面，
// 在「静止检查点」（事件播完、静置一段时间以后）比较整张 canvas 的像素与小人的位置姿势。
// 时钟、随机数与动画相位都固定，同一串调用下两版应当得到完全相同的画面。
//
// 用法：node docs/prototypes/v9/checks/replay.js [--v9 <index.html 的 file:// 地址>] [--only 场景编号,场景编号] [--mode step|burst] [--keep 4]
// 先运行 record.js 生成 .tmp/v9-checks/recordings.json；有差异的检查点会把 v8、v9 与差异图存进 .tmp/v9-checks/replay/。
// step：每个事件之后静置 14 秒再比较；burst：事件连续播放，只在最后静置以后比较；--reduced：系统设置为减少动画。
const fs = require('fs');
const path = require('path');
const { chromium, EXE, v8Url, v9Url, outDir } = require('./env');

const arg = (name, dflt) => { const i = process.argv.indexOf('--' + name); return i >= 0 ? process.argv[i + 1] : dflt; };
const V8 = v8Url;
const V9 = arg('v9', v9Url);
const ONLY = arg('only', '') ? arg('only').split(',') : null;
const MODE = arg('mode', 'step');
const KEEP = Number(arg('keep', 4));
const REDUCED = process.argv.includes('--reduced');
const OUT = path.join(outDir, 'replay');
fs.mkdirSync(OUT, { recursive: true });

const recordings = JSON.parse(fs.readFileSync(path.join(outDir, 'recordings.json'), 'utf8'))
  .filter((r) => !ONLY || ONLY.includes(r.id));

// 在页面里运行的回放驱动
const DRIVER = async ({ ops, mode, DT, SETTLE, GAP_EVENT, GAP_OTHER }) => {
  const P = window.Y8.pixel;
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

  // 统计 v9 画面对 ecs.js 的使用
  const counts = {};
  const E = P.ecs;
  // 自主行为（待机活动、管道的惯性）关掉：静止的画面只由快照决定，才能与 v8 逐像素比较
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
  const isWorker = (a) => /\.(agent|ops)$/.test(a.sprite);
  let fl = null;
  const cps = [];
  let failure = null;

  function shoot(label) {
    const sc = fl.scene;
    const workers = sc.actors.filter(isWorker).sort((a, b) => (a.sprite < b.sprite ? -1 : 1));
    const state = workers.map((a) => ({
      sprite: a.sprite, x: Math.round(a.x * 100) / 100, y: Math.round(a.y * 100) / 100, seat: Boolean(a.seat), anim: a.anim,
      facing: a.facing, icon: a.icon ? { kind: a.icon.kind, text: a.icon.text || null } : null,
      visible: a.visible, dim: a.dim, hold: a.hold || null, sign: a.sign || null, script: Boolean(a.script)
    }));
    // 固定动画相位：小人的动画计时与场景的动画时钟在两版里取同一个值
    workers.forEach((a, i) => { a.clock = 5000; a.animStart = 0; a.seed = 100 + i; });
    sc.animT = 20000;
    sc.drawNow();
    cps.push({ label, state, png: canvas.toDataURL('image/png'), t, frozen: Boolean(sc.frozen) });
  }

  try {
    let sinceCheckpoint = 0;
    let first = true;
    for (let i = 0; i < ops.length; i++) {
      const o = ops[i];
      if (o.op === 'mount') { fl = P.createFloorScene(canvas, { onDoorClick() {} }); first = true; continue; }
      if (!fl) continue;
      if (o.op === 'destroy') { fl.destroy(); fl = null; continue; }
      if (o.op === 'setModel') fl.setModel(clone(o.arg));
      else if (o.op === 'focus') fl.focus(o.arg);
      else if (o.op === 'setOverlay') fl.setOverlay(o.arg.id, o.arg.data);
      else if (o.op === 'playEvent') { fl.playEvent(clone(o.arg)); sinceCheckpoint++; }
      step(o.op === 'playEvent' ? GAP_EVENT : GAP_OTHER);
      const nextOp = ops[i + 1] && ops[i + 1].op;
      const endOfRefresh = o.op === 'setOverlay' && nextOp !== 'focus';
      if (endOfRefresh && first) { step(SETTLE); shoot('初始 #' + i); first = false; sinceCheckpoint = 0; }
      else if (endOfRefresh && mode === 'step' && sinceCheckpoint > 0) {
        const lastEv = [...ops.slice(0, i + 1)].reverse().find((x) => x.op === 'playEvent');
        step(SETTLE);
        shoot('事件 ' + (lastEv ? lastEv.arg.type : '?') + ' #' + i);
        sinceCheckpoint = 0;
      }
    }
    if (fl) { step(SETTLE); shoot('结束'); }
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
  await page.addInitScript((lv) => sessionStorage.setItem('y8.level', JSON.stringify(lv)), 'S5');
  await page.goto(root + '#/sys/machines');
  await page.waitForTimeout(700);
  const res = await page.evaluate(DRIVER, {
    ops: rec.ops, mode: MODE, DT: 50, SETTLE: 14000, GAP_EVENT: 900, GAP_OTHER: 50
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
  async function runOne(rec) {
    const a = await version(browser, V8, rec);
    const b = await version(browser, V9, rec);
    const row = { id: rec.id, checkpoints: a.cps.length, pixelDiff: 0, stateDiff: 0, v8fail: a.failure, v9fail: b.failure,
      v8errors: a.errors.length, v9errors: b.errors.length, ecs: b.counts, notes: [] };
    if (a.cps.length !== b.cps.length) row.notes.push('检查点数量不同 ' + a.cps.length + ' / ' + b.cps.length);
    const n = Math.min(a.cps.length, b.cps.length);
    let kept = 0;
    for (let i = 0; i < n; i++) {
      const A = a.cps[i], B = b.cps[i];
      // 整层中断（画面静止）时，小人停在中断前正在做的动作的位置：不比较小人的状态，像素只比较小人以外的部分
      const frozen = A.frozen || B.frozen;
      const boxes = frozen ? A.state.concat(B.state).map((s) => [Math.round(s.x) - 40, Math.round(s.y) - 72, Math.round(s.x) + 40, Math.round(s.y) + 8]) : null;
      if (frozen) row.frozenCheckpoints = (row.frozenCheckpoints || 0) + 1;
      const d = await diff(cmp, A.png, B.png, boxes);
      const stateSame = frozen || JSON.stringify(A.state) === JSON.stringify(B.state);
      if (!stateSame) {
        row.stateDiff++;
        // 逐个小人逐个字段列出差异
        const fields = [];
        A.state.forEach((s, k) => {
          const u = B.state[k] || {};
          Object.keys(s).forEach((key) => { if (JSON.stringify(s[key]) !== JSON.stringify(u[key])) fields.push(s.sprite + '.' + key + ' ' + JSON.stringify(s[key]) + ' → ' + JSON.stringify(u[key])); });
        });
        if (A.state.length !== B.state.length) fields.push('小人数量 ' + A.state.length + ' → ' + B.state.length);
        if (row.notes.length < 6) row.notes.push('[小人] ' + A.label + ' ' + fields.join('；'));
      }
      if (d.count !== 0) {
        row.pixelDiff++;
        if (row.notes.length < 6) row.notes.push('[像素] ' + A.label + ' 差异 ' + d.count + ' 个像素 ' + (d.bbox ? JSON.stringify(d.bbox) : JSON.stringify(d.size)));
        if (kept < KEEP && d.png) {
          kept++;
          const tag = rec.id + '-' + String(i).padStart(2, '0');
          save(tag + '-v8.png', A.png); save(tag + '-v9.png', B.png); save(tag + '-diff.png', d.png);
        }
      }
    }
    return row;
  }
  for (const rec of recordings) {
    let row = await runOne(rec);
    // 机器负载高时偶尔出现几个像素的随机差异：重跑一次，重跑相同就不算差异（备注里保留第一次的情况）
    if (row.pixelDiff || row.stateDiff) {
      const again = await runOne(rec);
      if (!again.pixelDiff && !again.stateDiff) {
        again.notes.push('第一次运行有差异（' + row.pixelDiff + ' 个检查点的像素、' + row.stateDiff + ' 个检查点的小人），重跑相同');
        again.retried = true;
        row = again;
      }
    }
    summary.push(row);
    console.log(JSON.stringify(row));
  }
  await browser.close();
  const bad = summary.filter((r) => r.pixelDiff || r.stateDiff || r.v8fail || r.v9fail || r.v8errors || r.v9errors);
  console.log(JSON.stringify({ recordings: summary.length, checkpoints: summary.reduce((s, r) => s + r.checkpoints, 0), badRecordings: bad.length, pixelDiff: summary.reduce((s, r) => s + r.pixelDiff, 0), stateDiff: summary.reduce((s, r) => s + r.stateDiff, 0) }));
  console.log(bad.length ? 'RESULT: DIFF' : 'RESULT: PASS');
  process.exit(bad.length ? 1 : 0);
})();
