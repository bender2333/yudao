// 录制：在 v8 页面里播放全部场景，记录项目楼层画面（createFloorScene）收到的每一次调用，
// 之后由 replay.js 把同一串调用按确定的时钟回放给 v8 与 v9 的楼层画面，比较结果。
// 用法：node docs/prototypes/v9/checks/record.js [--root <index.html 的 file:// 地址，默认是 v8>] [--out 文件名，默认 recordings.json]
// 写出 .tmp/v9-checks/<文件名>。在 v8 页面上录的调用给 replay.js 与 v8 逐像素比较；在 v9 页面上录的调用带着部门角色，给 life.js 看多角色。
const fs = require('fs');
const path = require('path');
const { chromium, EXE, v8Url, outDir } = require('./env');

const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i >= 0 ? process.argv[i + 1] : d; };
const ROOT = arg('root', v8Url);
const OUT = path.join(outDir, arg('out', 'recordings.json'));

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(() => sessionStorage.setItem('y8.level', JSON.stringify('S5')));
  await page.goto(ROOT + '#/home');
  await page.waitForTimeout(900);

  // 先离开楼层页，再装上包装，让下一次挂载被记录
  await page.evaluate(async () => {
    window.Y8.go('#/sys/machines');
    await new Promise((r) => setTimeout(r, 400));
    const P = window.Y8.pixel;
    window.__rec = null;
    const orig = P.createFloorScene;
    P.createFloorScene = function wrapped(canvas, opts) {
      const obj = orig.call(this, canvas, opts);
      const push = (op, arg) => { if (window.__rec) window.__rec.push({ op, arg: arg === undefined ? null : JSON.parse(JSON.stringify(arg)) }); };
      push('mount');
      ['setModel', 'playEvent', 'focus', 'setOverlay'].forEach((name) => {
        const f = obj[name];
        obj[name] = function () {
          if (name === 'setOverlay') push(name, { id: arguments[0], data: arguments[1] });
          else push(name, arguments[0]);
          return f.apply(this, arguments);
        };
      });
      const d = obj.destroy;
      obj.destroy = function () { push('destroy'); return d.apply(this, arguments); };
      return obj;
    };
  });

  const scenarios = await page.evaluate(() => window.Y8.backend.scenarios().map((s) => {
    const m = /^#\/p\/([^/]+)\//.exec(s.go || '');
    let pid = m ? m[1] : null;
    if (!pid) {
      const ev = s.steps.map((st) => st.event && st.event.project_id).find(Boolean);
      pid = ev || null;
    }
    return { id: s.id, name: s.name, level: s.level, go: s.go, pid, steps: s.steps.length };
  }));

  const recordings = [];
  for (const sc of scenarios) {
    if (!sc.pid) { console.log('跳过（没有项目）', sc.id); continue; }
    const rec = await page.evaluate(async ({ sid, pid }) => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const overview = '#/p/' + pid + '/overview';
      window.__rec = [];
      window.Y8.scenario.select(sid);
      await sleep(350);
      if (location.hash !== overview) window.Y8.go(overview);
      await sleep(600);
      const total = window.Y8.scenario.current().steps.length;
      let guard = 0;
      while (window.Y8.scenario.state().step < total && guard++ < 90) {
        window.Y8.scenario.step();
        await sleep(420);
        if (location.hash !== overview) { window.Y8.go(overview); await sleep(400); }
      }
      await sleep(600);
      const out = window.__rec;
      window.__rec = null;
      return out;
    }, { sid: sc.id, pid: sc.pid });
    recordings.push({ id: sc.id, name: sc.name, level: sc.level, project: sc.pid, ops: rec });
    const counts = rec.reduce((m, r) => { m[r.op] = (m[r.op] || 0) + 1; return m; }, {});
    console.log(sc.id, sc.pid, JSON.stringify(counts));
  }
  await browser.close();
  fs.writeFileSync(OUT, JSON.stringify(recordings));
  console.log('写入', OUT, Math.round(fs.statSync(OUT).size / 1024) + ' KB', '控制台错误', errors.length);
  if (errors.length) console.log(errors.slice(0, 5));
})();
