// 用法：node docs/prototypes/v12/checks/walkers.js
// 楼里小人的运行时验证：走位与待机动画确实由 ecs.js 的 stepCharacters 推进
// 在页面里另建一个楼场景，采样 actor 的 id、位置、动画名、速度与朝向
const { chromium, EXE, v12Url } = require('./env.js');

const ROOT = v12Url;

function floor(pid, lit) {
  return {
    project_id: pid, name: pid, status: 'running',
    lit: { product: false, engineering: false, quality: false, operations: false, ...lit },
    has_ops: false, flags: [], valve_closed: false, machine_ids: [], link_active: false,
    decisions: 0, runtime_machine: null
  };
}

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    console.log('CONSOLE@', JSON.stringify(msg.location()), JSON.stringify(msg.text()).slice(0, 240));
    errors.push(msg.text());
  });
  page.on('pageerror', (err) => { console.log('PAGEERROR@', String((err && err.stack) || err).slice(0, 400)); errors.push(String(err)); });
  await page.addInitScript(() => sessionStorage.setItem('y12.level', JSON.stringify('3.2C')));
  await page.goto(ROOT + '#/home');
  await page.waitForTimeout(900);

  const probe = await page.evaluate(async ({ floorsJson }) => {
    const host = document.createElement('div');
    host.style.cssText = 'position:fixed;left:0;top:0;width:640px;height:640px;z-index:9999';
    const canvas = document.createElement('canvas');
    host.appendChild(canvas);
    document.body.appendChild(host);
    const building = window.Y12.pixel.createBuildingScene(canvas, {});
    building.setModel({ floors: JSON.parse(floorsJson), show_basement: false });
    const sc = building.scene;
    const sample = () => sc.actors.filter((a) => a.data.walker).map((a) => ({
      id: a.id, x: Math.round(a.x), y: Math.round(a.y), anim: a.anim,
      speed: a.speed, moving: !!a.script
    }));
    const first = sample();
    const seenAnim = new Set(first.map((a) => a.anim));
    let moved = 0, speeds = new Set();
    const start = first.map((a) => a.x);
    for (let k = 0; k < 16; k++) {
      await new Promise((r) => setTimeout(r, 250));
      sample().forEach((a, i) => {
        if (Math.abs(a.x - start[i]) > 1) moved++;
        seenAnim.add(a.anim);
        speeds.add(a.speed);
      });
    }
    // 层数减少后旧的 actor 与角色实体要一并清掉
    building.setModel({ floors: [JSON.parse(floorsJson)[0]], show_basement: false });
    await new Promise((r) => setTimeout(r, 200));
    const afterShrink = sc.actors.filter((a) => a.data.walker).map((a) => a.id);
    building.destroy();
    host.remove();
    return {
      first, moved, anims: Array.from(seenAnim), speeds: Array.from(speeds),
      afterShrink, ids: first.map((a) => a.id)
    };
  }, { floorsJson: JSON.stringify([floor('p-a', {}), floor('p-b', { engineering: true }), floor('p-c', {})]) });

  // 单独验证：门口站定后面向左（facing = -1），空闲层会在多个随机位置之间走动
  const facing = await page.evaluate(async () => {
    const host = document.createElement('div');
    host.style.cssText = 'position:fixed;left:0;top:0;width:640px;height:400px;z-index:9999';
    const canvas = document.createElement('canvas');
    host.appendChild(canvas);
    document.body.appendChild(host);
    const building = window.Y12.pixel.createBuildingScene(canvas, {});
    building.setModel({
      floors: [
        { project_id: 'p-a', name: 'p-a', status: 'running',
          lit: { product: false, engineering: false, quality: true, operations: false },
          has_ops: false, flags: [], valve_closed: false, machine_ids: [], link_active: false,
          decisions: 0, runtime_machine: null },
        { project_id: 'p-b', name: 'p-b', status: 'idle',
          lit: { product: false, engineering: false, quality: false, operations: false },
          has_ops: false, flags: [], valve_closed: false, machine_ids: [], link_active: false,
          decisions: 0, runtime_machine: null }
      ], show_basement: false
    });
    const sc = building.scene;
    const xs = new Set();
    let standing = null;
    for (let k = 0; k < 40; k++) {
      await new Promise((r) => setTimeout(r, 250));
      const b = sc.actors.find((a) => a.id === 'ch-p-b');
      if (b) xs.add(Math.round(b.x));
      const a = sc.actors.find((a) => a.id === 'ch-p-a');
      if (a && !a.script) standing = { x: Math.round(a.x), facing: a.facing, anim: a.anim, speed: a.speed };
    }
    building.destroy();
    host.remove();
    return { roamPositions: Array.from(xs), standing };
  });

  await browser.close();
  console.log(JSON.stringify({ probe, facing, errors }, null, 1));
  // 门口坐标：quality 是 ROOMS 第 3 项（下标 2），roomX(2)+40 = 150+192+40 = 382
  const ok = errors.length === 0 &&
    probe.ids.length === 3 && probe.ids.every((id) => id.startsWith('ch-')) &&
    probe.afterShrink.length === 1 &&
    probe.moved > 0 &&
    probe.anims.includes('idle') && probe.anims.includes('walk') &&
    probe.speeds.join() === '22,40' &&
    facing.standing && facing.standing.x === 382 &&
    facing.standing.facing === -1 && facing.standing.anim === 'idle' &&
    facing.roamPositions.length >= 3;
  console.log(ok ? 'RESULT: PASS' : 'RESULT: FAIL');
  process.exit(ok ? 0 : 1);
})();
