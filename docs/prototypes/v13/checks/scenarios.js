// 用法：node docs/prototypes/v13/checks/scenarios.js
// 场景播放验证：逐个选择全部场景，按步骤播到最后一步，统计控制台错误与页面异常
// 同时统计楼（building.play）与机房（room.play）实际收到的动作数，保证首页的播放路径被走到；
// 机房只收机器事件翻成的动作，场景里没有在首页上发机器事件，机房的动作由 playback.js 核对
const { chromium, EXE, v13Url } = require('./env.js');

const ROOT = v13Url;

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    console.log('CONSOLE@', JSON.stringify(msg.location()), JSON.stringify(msg.text()).slice(0, 240));
    errors.push(msg.text());
  });
  page.on('pageerror', (err) => { console.log('PAGEERROR@', String((err && err.stack) || err).slice(0, 400)); errors.push(String(err)); });
  await page.addInitScript(() => sessionStorage.setItem('y13.level', JSON.stringify('S5')));
  await page.goto(ROOT + '#/home');
  await page.waitForTimeout(900);

  // 先离开首页再回来，让楼与机房在包装之后重新挂载；计数器统计画面收到的动作（play，画面合同的动作）
  await page.evaluate(async () => {
    window.Y13.go('#/sys/machines');
    await new Promise((r) => setTimeout(r, 500));
    const P = window.Y13.pixel;
    const cnt = window.__cnt = { buildingMount: 0, roomMount: 0, buildingPlay: 0, roomPlay: 0 };
    const wrap = (name, key) => {
      const orig = P[name];
      P[name] = function wrapped() {
        const obj = orig.apply(this, arguments);
        cnt[key + 'Mount']++;
        const origPlay = obj.play;
        obj.play = function (a) { cnt[key + 'Play']++; return origPlay.call(this, a); };
        return obj;
      };
    };
    wrap('createBuildingScene', 'building');
    wrap('createMachineRoomScene', 'room');
    window.Y13.go('#/home');
    await new Promise((r) => setTimeout(r, 500));
    // 记录访问过的路由
    window.__seen = new Set([location.hash]);
    const track = () => window.__seen.add(location.hash);
    window.addEventListener('hashchange', track);
    window.Y13.bus.on('route-changed', track);
  });

  const ids = await page.evaluate(() => window.Y13.backend.scenarios().map((s) => ({ id: s.id, name: s.name, level: s.level })));
  const report = [];
  for (const sc of ids) {
    const res = await page.evaluate(async (sid) => {
      window.Y13.scenario.select(sid);
      const total = window.Y13.scenario.current().steps.length;
      let guard = 0;
      while (window.Y13.scenario.state().step < total && guard++ < 90) {
        window.Y13.scenario.step();
        await new Promise((r) => setTimeout(r, 340));
      }
      return { total, reached: window.Y13.scenario.state().step, routes: Array.from(window.__seen) };
    }, sc.id);
    report.push({
      id: sc.id, name: sc.name, level: sc.level, total: res.total, reached: res.reached,
      home: res.routes.includes('#/home'), machines: res.routes.includes('#/sys/machines')
    });
    await page.waitForTimeout(120);
  }
  const cnt = await page.evaluate(() => window.__cnt);
  await browser.close();

  const unfinished = report.filter((r) => r.reached < r.total);
  console.log(JSON.stringify(report, null, 1));
  console.log(JSON.stringify({
    scenarios: report.length, unfinished: unfinished.length,
    homeScenes: report.filter((r) => r.home).length,
    machineScenes: report.filter((r) => r.machines).length,
    events: cnt, errors: errors.length
  }));
  const ok = errors.length === 0 && report.length === 25 && unfinished.length === 0 &&
    cnt.buildingPlay > 0;
  console.log(ok ? 'RESULT: PASS' : 'RESULT: FAIL ' + JSON.stringify({ unfinished, cnt }));
  process.exit(ok ? 0 : 1);
})();
