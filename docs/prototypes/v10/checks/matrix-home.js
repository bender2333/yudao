// 用法：node docs/prototypes/v10/checks/matrix-home.js
// 首页与机器页的验收矩阵：十档 × (#/home、#/sys/machines) × (1440、390) × (浅色、深色) 共 80 组
// 每组要求控制台错误与页面异常为零，且页面没有横向溢出
const path = require('path');
const { chromium, EXE, v10Url } = require('./env.js');

const ROOT = v10Url;
const LEVELS = ['ui', '3.1', '3.2C', '3.4A', '3.8', '3.2B', '3.2D', 'pilot', 'S4', 'S5'];
const ROUTES = ['#/home', '#/sys/machines'];
const WIDTHS = [1440, 390];
const THEMES = ['light', 'dark'];

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const results = [];
  for (const level of LEVELS) {
    for (const route of ROUTES) {
      for (const width of WIDTHS) {
        for (const theme of THEMES) {
          const ctx = await browser.newContext({ viewport: { width, height: width > 500 ? 900 : 844 } });
          const page = await ctx.newPage();
          const errors = [];
          page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
          page.on('pageerror', (err) => errors.push(String((err && err.stack) || err)));
          await page.addInitScript(([lv, th]) => {
            sessionStorage.setItem('y10.level', JSON.stringify(lv));
            localStorage.setItem('y10.theme', JSON.stringify(th));
          }, [level, theme]);
          await page.goto(ROOT + route);
          await page.waitForTimeout(1100);
          // 首页的楼里小人由 ECS.stepCharacters 推进：再等 1600 毫秒让走位动画跑起来
          if (route === '#/home') await page.waitForTimeout(1600);
          const overflow = await page.evaluate(() =>
            document.documentElement.scrollWidth > document.documentElement.clientWidth);
          results.push({ level, route, width, theme, errors: errors.length, overflow, detail: errors.slice(0, 3) });
          if (errors.length || overflow) {
            console.log('FAIL', JSON.stringify(results[results.length - 1]));
          }
          await ctx.close();
        }
      }
    }
  }
  await browser.close();
  const bad = results.filter((r) => r.errors || r.overflow);
  console.log(JSON.stringify({ total: results.length, failed: bad.length }, null, 1));
  if (bad.length) { console.log('FAILED CASES:'); bad.forEach((b) => console.log(JSON.stringify(b))); process.exit(1); }
})();
