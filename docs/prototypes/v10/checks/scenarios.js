// 用法：node docs/prototypes/v10/checks/scenarios.js
// 场景播放验证：逐个选择全部场景，按步骤播到最后一步，统计控制台错误与页面异常
// 同时统计楼（building.playEvent）与机房（room.playEvent）实际收到的事件数，
// 保证涉及首页与机房的播放路径被走到
const { chromium, EXE, v10Url } = require('./env.js');

const ROOT = v10Url;

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
  await page.addInitScript(() => sessionStorage.setItem('y10.level', JSON.stringify('S5')));
  await page.goto(ROOT + '#/home');
  await page.waitForTimeout(900);

  // 先离开首页再回来，让楼与机房在包装之后重新挂载；计数器统计 playEvent 的调用
  await page.evaluate(async () => {
    window.Y10.go('#/sys/machines');
    await new Promise((r) => setTimeout(r, 500));
    const P = window.Y10.pixel;
    const cnt = window.__cnt = { buildingMount: 0, roomMount: 0, buildingPlay: 0, roomPlay: 0 };
    const wrap = (name, key) => {
      const orig = P[name];
      P[name] = function wrapped() {
        const obj = orig.apply(this, arguments);
        cnt[key + 'Mount']++;
        const origPlay = obj.playEvent;
        obj.playEvent = function (ev) { cnt[key + 'Play']++; return origPlay.call(this, ev); };
        return obj;
      };
    };
    wrap('createBuildingScene', 'building');
    wrap('createMachineRoomScene', 'room');
    window.Y10.go('#/home');
    await new Promise((r) => setTimeout(r, 500));
    // 记录访问过的路由
    window.__seen = new Set([location.hash]);
    const track = () => window.__seen.add(location.hash);
    window.addEventListener('hashchange', track);
    window.Y10.bus.on('route-changed', track);
  });

  const ids = await page.evaluate(() => window.Y10.backend.scenarios().map((s) => ({ id: s.id, name: s.name, level: s.level })));
  const report = [];
  for (const sc of ids) {
    const res = await page.evaluate(async (sid) => {
      window.Y10.scenario.select(sid);
      const total = window.Y10.scenario.current().steps.length;
      let guard = 0;
      while (window.Y10.scenario.state().step < total && guard++ < 90) {
        window.Y10.scenario.step();
        await new Promise((r) => setTimeout(r, 340));
      }
      return { total, reached: window.Y10.scenario.state().step, routes: Array.from(window.__seen) };
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
  const ok = errors.length === 0 && report.length === 21 && unfinished.length === 0 &&
    cnt.buildingPlay > 0 && cnt.roomPlay > 0;
  console.log(ok ? 'RESULT: PASS' : 'RESULT: FAIL ' + JSON.stringify({ unfinished, cnt }));
  process.exit(ok ? 0 : 1);
})();
