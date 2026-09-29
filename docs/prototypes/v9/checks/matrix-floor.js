// 用法：node docs/prototypes/v9/checks/matrix-floor.js
// 项目概览页（挂载项目楼层画面）：九档 × 四个项目 × (1440、390) × (浅色、深色) 共 144 组，
// 每组要求控制台错误与页面异常为零，页面没有横向溢出，且楼层画面确实画出了内容
const { chromium, EXE, v9Url } = require('./env.js');

const LEVELS = ['ui', '3.1', '3.2C', '3.4A', '3.8', '3.2B', '3.2D', 'S4', 'S5'];
const PROJECTS = ['p-todo', 'p-metro', 'p-sensor', 'p-agents'];
const WIDTHS = [1440, 390];
const THEMES = ['light', 'dark'];

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const bad = [];
  let total = 0;
  for (const level of LEVELS) {
    for (const pid of PROJECTS) {
      for (const width of WIDTHS) {
        for (const theme of THEMES) {
          const ctx = await browser.newContext({ viewport: { width, height: width > 500 ? 900 : 844 } });
          const page = await ctx.newPage();
          const errors = [];
          page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
          page.on('pageerror', (e) => errors.push(String((e && e.stack) || e).slice(0, 300)));
          await page.addInitScript(([lv, th]) => {
            sessionStorage.setItem('y8.level', JSON.stringify(lv));
            localStorage.setItem('y8.theme', JSON.stringify(th));
          }, [level, theme]);
          await page.goto(v9Url + '#/p/' + pid + '/overview');
          await page.waitForTimeout(1300);
          const info = await page.evaluate(() => {
            const cv = document.querySelector('.y8-floor-wrap canvas');
            let ink = 0;
            if (cv) {
              const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
              for (let i = 0; i < d.length; i += 64) if (d[i] + d[i + 1] + d[i + 2] > 60) ink++;
            }
            return { hasFloor: Boolean(cv), ink, overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth };
          });
          total++;
          if (errors.length || info.overflow || (info.hasFloor && info.ink < 500)) bad.push({ level, pid, width, theme, errors: errors.slice(0, 2), info });
          await ctx.close();
        }
      }
    }
  }
  await browser.close();
  console.log(JSON.stringify({ total, failed: bad.length }));
  bad.slice(0, 10).forEach((b) => console.log('FAIL', JSON.stringify(b)));
  process.exit(bad.length ? 1 : 0);
})();
