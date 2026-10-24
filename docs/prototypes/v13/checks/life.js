// 事件过程截图：按固定时钟回放录制的楼层调用，在指定事件发生之后每隔一段时间截一帧，拼成一张联系表。
// 录制是 record.js 在 v12 上录下的（.tmp/v13-checks/recordings.json）；v13 的画面只认画面合同，
// 回放时录到的查询结果和事件经过真正的翻译层（js/translate/）再交给它：查询结果翻成状态，事件翻成动作。
// 用法：先运行 record.js；
//   node docs/prototypes/v13/checks/life.js --rec sc-todo-loop --event transition --nth 1 --frames 12 --interval 300 [--root <index.html 的 file:// 地址>] [--out 文件名] [--recs 录制文件名]
// --root 默认是 v13；指向 v12 的 index.html 时按 v12 的调用形状回放，两版的联系表可以对照。联系表存在 .tmp/v13-checks/。
// --event 取录制里的事件类型；transition 指部门之间的交接，v13 里是翻出交接（handoff）动作的那条事件（transition 本身 v13 不再放）。
// --event idle 不放事件，观察待机时小人的走动。
// 事件之前先静置，画面回到静止状态；事件放进去以后，紧跟着的那次刷新（状态）也送进去，页面就是先事件后刷新。
// v13 的状态要等位置不大于它的动作演完才上画面，所以事件过程的头几帧是动作，状态变化在动作演完以后出现。联系表不开覆盖层。
const fs = require('fs');
const path = require('path');
const { chromium, EXE, v13Url, outDir, spaceOf } = require('./env.js');

const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i >= 0 ? process.argv[i + 1] : d; };
const REC = arg('rec', 'sc-todo-loop');
const EVENT = arg('event', 'transition');
const NTH = Number(arg('nth', 1));
const FRAMES = Number(arg('frames', 12));
const INTERVAL = Number(arg('interval', 300));
const ROOT = arg('root', v13Url);
const OUT = arg('out', 'life-' + REC + '-' + EVENT + '-' + NTH + '.png');
const rec = JSON.parse(fs.readFileSync(path.join(outDir, arg('recs', 'recordings.json')), 'utf8')).find((r) => r.id === REC);
if (!rec) throw new Error('没有这个录制：' + REC);

const DRIVER = async ({ ops, EVENT, NTH, FRAMES, INTERVAL, space }) => {
  const P = window[space].pixel;
  const v13 = space === 'Y13';
  let t = 0;
  const q = [];
  window.requestAnimationFrame = (cb) => { q.push(cb); return q.length; };
  window.cancelAnimationFrame = () => {};
  performance.now = () => t;
  let seed = 987654321;
  Math.random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const step = (ms) => { const n = Math.max(1, Math.round(ms / 50)); for (let i = 0; i < n; i++) { t += 50; const cbs = q.splice(0); for (const cb of cbs) cb(t); } };
  const host = document.createElement('div');
  host.style.cssText = 'position:fixed;left:0;top:0;width:640px;height:320px;z-index:99999;background:#000';
  const canvas = document.createElement('canvas');
  host.appendChild(canvas);
  document.body.appendChild(host);
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const isWorker = (a) => /\.(agent|ops|manager|architect|lead|explorer|reviewer|tester)$/.test(a.sprite);

  // v13：录到的 floorModel 与事件（v12 的说法）经过翻译层再交给画面合同的接口。
  // transition 与 collaboration_* 是 v12 的界面层派生出来的，翻译层自己从原始事件翻出交接，这里不重复放
  const adapt = (f) => {
    const T = window[space].translate;
    let pos = 0;
    let roles = [];
    let firstState = true;
    const names = { roleName: (id) => { const h = roles.find((r) => r.id === id || r.kind === id); return h ? h.name : null; } };
    const derived = (ev) => ev.type === 'transition' || /^collaboration_/.test(ev.type);
    f.setModel = (model) => {
      roles = Object.values(model.roles || {}).reduce((l, r) => l.concat(r), []);
      const s = T.floor.state({ position: ++pos, loop: model, roles: model.roles, focus: model.focus_id });
      if (firstState) { f.jump(s); firstState = false; } else f.setState(s);
      f.setDecisions(model.decisions || []);
    };
    f.playEvent = (ev) => {
      if (derived(ev)) return;
      const s = T.stream(ev);
      if (s) f.stream(s.who, s.text);
      T.floor.actions(Object.assign({ position: ++pos }, ev), names).forEach((a) => f.play(a));
    };
    // 这条事件会翻出哪些动作（不占位置）
    f.kindsOf = (ev) => (derived(ev) ? [] : T.floor.actions(Object.assign({ position: 0 }, ev), names).map((a) => a.kind));
    return f;
  };

  let fl = null;
  let seen = 0;
  const frames = [];
  const snap = (t0, ev) => {
    fl.scene.drawNow();
    frames.push({ t: t0, ev, url: canvas.toDataURL('image/png'),
      workers: fl.scene.actors.filter(isWorker).map((a) => [a.sprite.split('.')[0], Math.round(a.x), Math.round(a.y), a.anim]) });
  };
  const feed = (o) => {
    if (o.op === 'mount') { fl = P.createFloorScene(canvas, { onDoorClick() {} }); if (v13) fl = adapt(fl); return; }
    if (!fl) return;
    if (o.op === 'destroy') { fl.destroy(); fl = null; }
    else if (o.op === 'setModel') fl.setModel(clone(o.arg));
    else if (o.op === 'focus') fl.focus(o.arg);
    else if (o.op === 'playEvent') fl.playEvent(clone(o.arg));
  };
  // v13 里 transition 对应翻出交接动作的事件；其余按事件类型
  const KIND = EVENT === 'transition' ? 'handoff' : EVENT;
  const hitOf = (ev) => {
    if (!v13) return ev.type === EVENT;
    const kinds = fl.kindsOf(ev);
    return kinds.length > 0 && (ev.type === EVENT || kinds.includes(KIND));
  };

  for (let i = 0; i < ops.length; i++) {
    const o = ops[i];
    if (fl && o.op === 'playEvent' && hitOf(o.arg)) {
      seen++;
      if (seen === NTH) {
        // 事件到达前先静置，画面回到静止状态，再截事件过程
        step(6000);
        snap(0, o.arg.type + (v13 ? ' → ' + fl.kindsOf(o.arg).join('+') : '') + ' ' + JSON.stringify(o.arg.payload).slice(0, 60));
        feed(o);
        // 紧跟在事件后面的刷新（到 setOverlay 为止）一并送进去
        for (let j = i + 1; j < ops.length; j++) { feed(ops[j]); if (ops[j].op === 'setOverlay') break; }
        for (let k = 1; k <= FRAMES; k++) { step(INTERVAL); snap(k * INTERVAL); }
        return frames;
      }
    }
    feed(o);
    // 待机观察：第一份模型送进去以后，什么事件都不放，每隔一段时间截一帧
    if (EVENT === 'idle' && fl && o.op === 'setOverlay') {
      for (let k = 0; k <= FRAMES; k++) { if (k) step(INTERVAL); snap(k * INTERVAL); }
      return frames;
    }
    if (o.op !== 'mount') step(o.op === 'playEvent' ? 900 : 50);
  }
  return frames;
};

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  const { ns, prefix } = spaceOf(ROOT);
  await page.addInitScript(([key, lv]) => sessionStorage.setItem(key, JSON.stringify(lv)), [prefix + '.level', 'S5']);
  await page.goto(ROOT + '#/sys/machines');
  await page.waitForTimeout(600);
  const frames = await page.evaluate(DRIVER, { ops: rec.ops, EVENT, NTH, FRAMES, INTERVAL, space: ns });
  await ctx.close();
  if (!frames.length) { console.log('没有找到事件', EVENT, NTH); process.exit(1); }
  // 联系表：每帧裁出楼层中间的房间区域（y 从 20 到 250），两列排开
  const cmp = await browser.newPage();
  await cmp.goto('about:blank');
  const sheet = await cmp.evaluate(async (fr) => {
    const load = (src) => new Promise((res) => { const im = new Image(); im.onload = () => res(im); im.src = src; });
    const imgs = await Promise.all(fr.map((f) => load(f.url)));
    const cols = 2, w = 640, h = 240, pad = 14;
    const rows = Math.ceil(imgs.length / cols);
    const cv = document.createElement('canvas');
    cv.width = cols * w; cv.height = rows * (h + pad);
    const cx = cv.getContext('2d');
    cx.fillStyle = '#111'; cx.fillRect(0, 0, cv.width, cv.height);
    imgs.forEach((im, i) => {
      const x = (i % cols) * w, y = Math.floor(i / cols) * (h + pad);
      cx.drawImage(im, 0, 20, 640, h, x, y + pad, w, h);
      cx.fillStyle = '#ffd'; cx.font = '11px sans-serif';
      cx.fillText('t=' + fr[i].t + 'ms ' + (fr[i].ev || '') + ' ' + fr[i].workers.map((w2) => w2.join(':')).join(' '), x + 4, y + 11);
    });
    return cv.toDataURL('image/png');
  }, frames);
  fs.writeFileSync(path.join(outDir, OUT), Buffer.from(sheet.split(',')[1], 'base64'));
  console.log('写入', path.join(outDir, OUT), frames.length + ' 帧', '页面错误', errors.length);
  if (errors.length) console.log(errors.slice(0, 3));
  await browser.close();
  process.exit(errors.length ? 1 : 0);
})();
