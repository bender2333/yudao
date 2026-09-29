// 用法：node docs/prototypes/v9/checks/identity-building.js
// 楼与机房的确定性逐像素比较：在 v8 与 v9 的页面里用同一份数据建楼与机房，
// 冻结画面、把所有小人与时间基准摆成同一状态，再截同一块 canvas 逐像素比较。
// 楼里随时间变化的元素（状态灯闪动、管线流动、小人动画相位、随机走动位置）全部固定住之后，
// 两版画面应当完全相同；任何残余差异都是真实画面差异，不是动画相位差。
// 自检：同一份设置在同一版本里跑两次，第二次换时间基准，两次的画面必须不同（证明比较确实在看内容，
// 不会因两次都截到空白而假通过）。
const { chromium, EXE, v8Url, v9Url } = require('./env.js');

const V9 = v9Url;
const V8 = v8Url;

const SETUP = (opts) => {
  const ANIM = (opts && opts.animT) || 2400;
  // 自主行为（管线光点的惯性）关掉：静止的画面只由数据决定，才能与 v8 逐像素比较
  if (window.Y8.pixel.ecs) window.Y8.pixel.ecs.config.autonomy = false;
  const mk = (pid, lit, status, decisions) => ({
    project_id: pid, name: pid.toUpperCase(), status,
    lit: { product: false, engineering: false, quality: false, operations: false, ...lit },
    has_ops: false, flags: [], valve_closed: false, machine_ids: [], link_active: false,
    decisions: decisions || 0, runtime_machine: null
  });
  const floors = [mk('p-a', {}, 'running', 2), mk('p-b', { engineering: true }, 'waiting_slot'),
    mk('p-c', { quality: true, product: true }, 'idle'), mk('p-d', {}, 'pending_verification')];
  const room = {
    machines: [
      { id: 'm-host', kind: 'host', name: '家里主机', online: true, containers: 4,
        actions: [{ label: '跑测试', state: 'running' }], runtime_for: [{ name: '待办清单', version: 'v3' }],
        late_receipts: [1] },
      { id: 'm-desk', kind: 'desktop', name: '办公室台式机', online: true, containers: 0,
        actions: [{ label: '构建镜像', state: 'unknown' }], runtime_for: [], late_receipts: [] },
      { id: 'm-lap', kind: 'laptop', name: '笔记本', online: false, containers: 0, actions: [],
        runtime_for: [{ name: '地铁票价', version: 'r2' }], late_receipts: [] },
      { id: 'm-pi', kind: 'pi', name: '树莓派', online: true, containers: 2, actions: [{ label: '采集' }],
        runtime_for: [], late_receipts: [] }
    ],
    links: [{ machine_id: 'm-host', color_index: 0, active: true },
      { machine_id: 'm-desk', color_index: 1, active: true }, { machine_id: 'm-lap', color_index: 2, active: false }]
  };
  const box = (cls) => {
    const host = document.createElement('div');
    host.className = cls;
    host.style.cssText = 'position:fixed;left:0;top:0;width:640px;height:640px;z-index:9999;background:#000';
    const canvas = document.createElement('canvas');
    host.appendChild(canvas);
    document.body.appendChild(host);
    return { host, canvas };
  };
  const b = box('probe-building');
  const building = window.Y8.pixel.createBuildingScene(b.canvas, {});
  building.setModel({ floors, show_basement: true });
  const m = box('probe-room');
  const machine = window.Y8.pixel.createMachineRoomScene(m.canvas, { onMachineClick: () => {} });
  machine.setModel(room);
  const pin = (sc) => {
    sc.frozen = true;
    sc.reduced = false;
    sc.animT = ANIM;
    sc.realT = ANIM;
    sc.particles.length = 0;
    sc.flyers.length = 0;
    sc.timers.length = 0;
    sc.tweens.length = 0;
    sc.actors.forEach((a, i) => {
      a.script = null;
      a.step = null;
      a.x = 150 + i * 60;
      a.y = 34 + i * 66 + 60;
      a.anim = 'idle';
      a.facing = -1;
      a.clock = 0;
      a.hold = null;
      a.sign = null;
      a.bubble = null;
      a.icon = null;
    });
    sc.drawNow();
  };
  pin(building.scene);
  pin(machine.scene);
  return {
    reduced: [building.scene.reduced, machine.scene.reduced],
    frozen: [building.scene.frozen, machine.scene.frozen],
    scale: [building.scene.scale, machine.scene.scale],
    walkCount: building.scene.actors.length
  };
};

async function shoot(browser, root, sel, animT) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(root + '#/home');
  await page.waitForTimeout(900);
  const info = await page.evaluate(SETUP, { animT });
  const b = await page.locator(sel + ' >> nth=0').screenshot();
  const r = await page.locator('.probe-room canvas').screenshot();
  await ctx.close();
  return { building: b.toString('base64'), room: r.toString('base64'), errors, info };
}

async function analyse(cmp, aB64, bB64) {
  return cmp.evaluate(async ([a, b]) => {
    const load = (src) => new Promise((res) => {
      const img = new Image();
      img.onload = () => res(img);
      img.src = 'data:image/png;base64,' + src;
    });
    const [ia, ib] = await Promise.all([load(a), load(b)]);
    if (ia.width !== ib.width || ia.height !== ib.height) {
      return { mismatch: true, sizeA: [ia.width, ia.height], sizeB: [ib.width, ib.height] };
    }
    const cv = document.createElement('canvas');
    cv.width = ia.width; cv.height = ia.height;
    const cx = cv.getContext('2d');
    cx.drawImage(ia, 0, 0);
    const da = cx.getImageData(0, 0, ia.width, ia.height).data;
    cx.clearRect(0, 0, cv.width, cv.height);
    cx.drawImage(ib, 0, 0);
    const db = cx.getImageData(0, 0, ib.width, ib.height).data;
    let count = 0;
    let ink = 0;
    const coords = [];
    for (let y = 0; y < ia.height; y++) {
      for (let x = 0; x < ia.width; x++) {
        const i = (y * ia.width + x) * 4;
        if (da[i] + da[i + 1] + da[i + 2] > 40) ink++;
        if (da[i] !== db[i] || da[i + 1] !== db[i + 1] || da[i + 2] !== db[i + 2]) {
          count++;
          if (coords.length < 8) coords.push([x, y]);
        }
      }
    }
    return { width: ia.width, height: ia.height, diffPixels: count, inkPixels: ink, sample: coords };
  }, [aB64, bB64]);
}

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const cmp = await browser.newPage();
  await cmp.goto('about:blank');
  const v8a = await shoot(browser, V8, '.probe-building canvas', 2400);
  const v9a = await shoot(browser, V9, '.probe-building canvas', 2400);
  const v8b = await shoot(browser, V8, '.probe-building canvas', 5200);
  console.log('v8 info', JSON.stringify(v8a.info));
  console.log('v9 info', JSON.stringify(v9a.info));
  const b = await analyse(cmp, v8a.building, v9a.building);
  const r = await analyse(cmp, v8a.room, v9a.room);
  const self = await analyse(cmp, v8a.building, v8b.building);
  console.log('building', JSON.stringify(b));
  console.log('room', JSON.stringify(r));
  console.log('自检（同版本换时间基准）', JSON.stringify(self));
  await browser.close();
  const errors = v8a.errors.concat(v9a.errors);
  const sameShape = JSON.stringify(v8a.info) === JSON.stringify(v9a.info);
  const ok = errors.length === 0 && sameShape && !b.mismatch && !r.mismatch &&
    b.diffPixels === 0 && r.diffPixels === 0 &&
    // 自检：换时间基准后画面确有变化（状态灯与管线光点在闪），且画面确有内容（非空白）
    self.diffPixels > 0 && b.inkPixels > 10000 && r.inkPixels > 5000;
  console.log(ok ? 'RESULT: PASS 同一数据、同一时间基准、同一小人位置下，v8 与 v9 的楼画面与机房画面逐像素相同'
    : 'RESULT: FAIL');
  process.exit(ok ? 0 : 1);
})();
