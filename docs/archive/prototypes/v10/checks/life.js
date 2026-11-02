// 事件过程截图：按固定时钟回放录制的调用，在指定事件发生之后每隔一段时间截一帧，拼成一张联系表。
// 用法：先运行 record.js；node docs/prototypes/v10/checks/life.js --rec sc-todo-loop --event transition --nth 1 --frames 12 --interval 300 [--root file:///.../index.html] [--out 文件名] [--recs 录制文件名]
// --event idle 不放事件，观察待机时小人的走动；联系表存在 .tmp/v10-checks/。
const fs = require('fs');
const path = require('path');
const { chromium, EXE, v10Url, outDir, spaceOf } = require('./env.js');

const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i >= 0 ? process.argv[i + 1] : d; };
const REC = arg('rec', 'sc-todo-loop');
const EVENT = arg('event', 'transition');
const NTH = Number(arg('nth', 1));
const FRAMES = Number(arg('frames', 12));
const INTERVAL = Number(arg('interval', 300));
const ROOT = arg('root', v10Url);
const OUT = arg('out', 'life-' + REC + '-' + EVENT + '-' + NTH + '.png');
const rec = JSON.parse(fs.readFileSync(path.join(outDir, arg('recs', 'recordings.json')), 'utf8')).find((r) => r.id === REC);
if (!rec) throw new Error('没有这个录制：' + REC);

const DRIVER = async ({ ops, EVENT, NTH, FRAMES, INTERVAL, space }) => {
  const P = window[space].pixel;
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
  let fl = null;
  let seen = 0;
  const frames = [];
  const isWorker = (a) => /\.(agent|ops|manager|architect|lead|explorer|reviewer|tester)$/.test(a.sprite);
  for (let i = 0; i < ops.length; i++) {
    const o = ops[i];
    if (o.op === 'mount') { fl = P.createFloorScene(canvas, { onDoorClick() {} }); continue; }
    if (!fl) continue;
    if (o.op === 'destroy') { fl.destroy(); fl = null; continue; }
    if (o.op === 'setModel') fl.setModel(clone(o.arg));
    else if (o.op === 'focus') fl.focus(o.arg);
    else if (o.op === 'setOverlay') {
      fl.setOverlay(o.arg.id, o.arg.data);
      // 待机观察：第一份模型送进去以后，什么事件都不放，每隔一段时间截一帧
      if (EVENT === 'idle') {
        for (let k = 0; k <= FRAMES; k++) {
          if (k) step(INTERVAL);
          fl.scene.drawNow();
          frames.push({ t: k * INTERVAL, url: canvas.toDataURL('image/png'),
            workers: fl.scene.actors.filter(isWorker).map((a) => [a.sprite.split('.')[0], Math.round(a.x), Math.round(a.y), a.anim]) });
        }
        return frames;
      }
    } else if (o.op === 'playEvent') {
      const hit = o.arg.type === EVENT;
      if (hit) seen++;
      if (hit && seen === NTH) {
        // 事件到达前先静置，画面回到静止状态，再截事件过程
        step(6000);
        fl.scene.drawNow();
        frames.push({ t: 0, ev: o.arg.type + ' ' + JSON.stringify(o.arg.payload).slice(0, 60), url: canvas.toDataURL('image/png'),
          workers: fl.scene.actors.filter(isWorker).map((a) => [a.sprite.split('.')[0], Math.round(a.x), Math.round(a.y), a.anim]) });
        fl.playEvent(clone(o.arg));
        for (let k = 1; k <= FRAMES; k++) {
          step(INTERVAL);
          fl.scene.drawNow();
          frames.push({ t: k * INTERVAL, url: canvas.toDataURL('image/png'),
            workers: fl.scene.actors.filter(isWorker).map((a) => [a.sprite.split('.')[0], Math.round(a.x), Math.round(a.y), a.anim]) });
        }
        return frames;
      }
      fl.playEvent(clone(o.arg));
    }
    step(o.op === 'playEvent' ? 900 : 50);
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
  // 联系表：每帧裁出楼层中间的房间区域（y 从 20 到 250），三列排开
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
  await browser.close();
})();
