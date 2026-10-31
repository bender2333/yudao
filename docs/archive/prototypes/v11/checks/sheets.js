// 截图联系表（design.md 第 9 节）：自举试点首批画面，每个画面在两种宽度（1440、1920）与两种主题下各截一张，
// 存进 .tmp/v11-checks/sheets/，再拼成每个画面一张的联系表（左右为两种宽度，上下为浅色与深色），交给用户确认画面。
// 用法：node docs/prototypes/v11/checks/sheets.js [--only 画面名,画面名]
const fs = require('fs');
const path = require('path');
const { chromium, EXE, v11Url, outDir } = require('./env');

const OUT = path.join(outDir, 'sheets');
fs.mkdirSync(OUT, { recursive: true });
const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i >= 0 ? process.argv[i + 1] : d; };
const ONLY = arg('only', '') ? arg('only').split(',') : null;

const SIZES = [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }];
const THEMES = [['light', '浅色'], ['dark', '深色']];

// 在页面里做的准备：wait 毫秒、打开覆盖层、点开事实元素、播放场景、展开报告项，最后把要看的部分滚到窗口顶部
const STEPS = {
  overlay: async (p, id) => { await p.click('[data-overlay="' + id + '"]'); await p.waitForTimeout(700); },
  fact: async (p, kind) => { await p.evaluate((k) => window.Y11.scenes.activeFloor().floor.openFact(k), kind); await p.waitForTimeout(500); },
  scenario: async (p, id) => {
    await p.evaluate(async (sid) => {
      const Y = window.Y11;
      Y.scenario.select(sid);
      await new Promise((r) => setTimeout(r, 600));
      const total = Y.scenario.current().steps.length;
      while (Y.scenario.state().step < total) { Y.scenario.step(); await new Promise((r) => setTimeout(r, 500)); }
    }, id);
    await p.waitForTimeout(800);
  },
  act: async (p, spec) => { await p.evaluate((s) => window.Y11.actions.run(s.act, { dataset: s.data }, null), spec); await p.waitForTimeout(500); },
  scroll: async (p, selector) => {
    await p.evaluate((sel) => {
      const el = document.querySelector(sel);
      if (!el) throw new Error('找不到要截图的部分：' + sel);
      window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 70);
    }, selector);
    await p.waitForTimeout(500);
  }
};

const SCREENS = [
  { id: 'loops', name: '覆盖层「循环」', hash: '#/p/p-todo/overview?w=w-todo-csv', steps: [['overlay', 'loops'], ['scroll', '.y11-floor-wrap']] },
  { id: 'sources', name: '覆盖层「来源」', hash: '#/p/p-todo/overview', steps: [['overlay', 'sources'], ['scroll', '.y11-floor-wrap']] },
  { id: 'source-card', name: '来源卡片（点停放的包裹）', hash: '#/p/p-todo/overview', steps: [['overlay', 'sources'], ['fact', 'parcel'], ['scroll', '.y11-floor-wrap']] },
  { id: 'coverage', name: '覆盖层「检验」', hash: '#/p/p-todo/overview', steps: [['overlay', 'coverage'], ['scroll', '.y11-floor-wrap']] },
  { id: 'coverage-list', name: '覆盖层「检验」的逐条清单', hash: '#/p/p-todo/overview', steps: [['overlay', 'coverage'], ['fact', 'coverage'], ['scroll', '.y11-floor-wrap']] },
  { id: 'observe-loops', name: '观测页「循环」区块（展开一行）', hash: '#/home', steps: [['scenario', 'sc-todo-loops'], ['scroll', '#obs-loop']] },
  { id: 'materials-criteria', name: '资料页的逐条结论表', hash: '#/p/p-todo/materials?w=w-todo-base', steps: [['scroll', '#mt-qa']] },
  { id: 'report-changes', name: '离开期间的报告：收敛状态的变化', hash: '#/home', steps: [['act', { act: 'home.item', data: { item: 'loop_changes' } }], ['scroll', '#home-report']] },
  { id: 'report-open', name: '离开期间的报告：带开环条件的放行', hash: '#/home', steps: [['act', { act: 'home.item', data: { item: 'open_releases' } }], ['scroll', '#home-report']] }
];

async function shoot(browser, screen, size, theme) {
  const ctx = await browser.newContext({ viewport: size });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.addInitScript(([th]) => {
    sessionStorage.setItem('y11.level', JSON.stringify('pilot'));
    localStorage.setItem('y11.theme', JSON.stringify(th));
  }, [theme]);
  await page.goto(v11Url + screen.hash);
  await page.waitForTimeout(1300);
  // 原型工具条盖在页面底部，截图时收起
  await page.addStyleTag({ content: '#y11-toolbar { display: none !important; } :root { --tb-space: 0px !important; }' });
  for (const [kind, value] of screen.steps) await STEPS[kind](page, value);
  const file = path.join(OUT, screen.id + '-' + size.width + '-' + theme + '.png');
  await page.screenshot({ path: file });
  await ctx.close();
  return { file, errors };
}

// 拼成 2×2 的联系表：左右为两种宽度，上下为浅色与深色；每格缩到 960 宽
async function sheet(browser, screen, shots) {
  const page = await browser.newPage();
  const cells = shots.map((s) => ({ label: s.label, data: 'data:image/png;base64,' + fs.readFileSync(s.file).toString('base64') }));
  const png = await page.evaluate(async ({ title, cells }) => {
    const load = (src) => new Promise((res) => { const im = new Image(); im.onload = () => res(im); im.src = src; });
    const ims = await Promise.all(cells.map((c) => load(c.data)));
    const CW = 960, PAD = 16, HEAD = 44, LAB = 26;
    const hs = ims.map((im) => Math.round((im.height * CW) / im.width));
    const rowH = [Math.max(hs[0], hs[1]), Math.max(hs[2], hs[3])];
    const cv = document.createElement('canvas');
    cv.width = PAD * 3 + CW * 2;
    cv.height = HEAD + PAD + (LAB + rowH[0]) + PAD + (LAB + rowH[1]) + PAD;
    const c = cv.getContext('2d');
    c.fillStyle = '#e9ecef'; c.fillRect(0, 0, cv.width, cv.height);
    c.fillStyle = '#1f2230'; c.font = '600 22px "Microsoft YaHei", sans-serif'; c.textBaseline = 'middle';
    c.fillText('原型 v11 · ' + title, PAD, HEAD / 2 + 4);
    ims.forEach((im, i) => {
      const col = i % 2, row = Math.floor(i / 2);
      const x = PAD + col * (CW + PAD);
      const y = HEAD + PAD + (row ? LAB + rowH[0] + PAD : 0);
      c.fillStyle = '#495057'; c.font = '15px "Microsoft YaHei", sans-serif';
      c.fillText(cells[i].label, x, y + LAB / 2);
      c.drawImage(im, x, y + LAB, CW, hs[i]);
      c.strokeStyle = '#adb5bd'; c.strokeRect(x - 0.5, y + LAB - 0.5, CW + 1, hs[i] + 1);
    });
    return cv.toDataURL('image/png');
  }, { title: screen.name, cells });
  await page.close();
  const file = path.join(OUT, screen.id + '.png');
  fs.writeFileSync(file, Buffer.from(png.split(',')[1], 'base64'));
  return file;
}

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const made = [];
  let errorCount = 0;
  for (const screen of SCREENS.filter((s) => !ONLY || ONLY.includes(s.id))) {
    const shots = [];
    for (const [theme, themeName] of THEMES) {
      for (const size of SIZES) {
        const r = await shoot(browser, screen, size, theme);
        if (r.errors.length) console.log('ERRORS', screen.id, size.width, theme, r.errors.slice(0, 3));
        errorCount += r.errors.length;
        shots.push({ file: r.file, label: '宽度 ' + size.width + ' · ' + themeName });
      }
    }
    made.push(await sheet(browser, screen, shots));
    console.log('联系表', screen.name, made[made.length - 1]);
  }
  await browser.close();
  console.log(JSON.stringify({ sheets: made.length, errors: errorCount }));
  console.log(errorCount ? 'RESULT: FAIL' : 'RESULT: PASS');
  process.exit(errorCount ? 1 : 0);
})();
