// 楼层画面的调用录制（工单 #957；原型 v13 的页面与翻译层，做法照 docs/prototypes/v13/checks/record.js）：
// 在 v13 的页面上逐个播放场景，录下项目楼层画面收到的状态、实时内容与页面收到的事件。
//
// 录的是 Yudao 的说法：状态是 v13 的翻译层从查询结果（project.loop）翻好、交给画面的画面合同状态，
// 事件是页面收到的原始事件（带位置、工具名已经是 bash），回放时由客户端的翻译层翻成动作。
//
// 每段录制要在回放时比的是最后一个检查点：事件播完、时间线放空以后，与 v13 的画面逐像素、逐个小人相同，
// 所以录制里只存调用，不存状态与截图；比较在 tests/helpers/floor-replay.ts 里做。
//
// 录下的调用序列存入客户端的测试目录（tests/fixtures/floor/recordings.json），
// 只经重写开关更新（--write 时才写；否则只比较，不一致时报错）。
//
// 用法：node client/scripts/record-floor-calls.mjs [--write]
// 需要 Playwright 的 Chromium（PLAYWRIGHT_PATH 可以指定位置，CHROMIUM_EXE 指定可执行文件）。

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..");
const repoRoot = resolve(clientRoot, "..");
const outDir = join(clientRoot, "tests", "fixtures", "floor");
const outFile = join(outDir, "recordings.json");
const ROOT = pathToFileURL(join(repoRoot, "docs", "prototypes", "v13", "index.html")).href;

const args = process.argv.slice(2);
const WRITE = args.includes("--write");

const playwrightPath = process.env.PLAYWRIGHT_PATH
  || join(repoRoot, ".tmp", "v8", "pw", "node_modules", "playwright");
let chromium;
if (existsSync(playwrightPath)) {
  chromium = require(playwrightPath).chromium;
} else {
  ({ chromium } = await import("@playwright/test"));
}
const EXE = process.env.CHROMIUM_EXE || "C:/Users/BA_H3C_Pad/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe";

/** 场景编号上限：编号 20 以上的场景是自举试点与新画面的，只录现有测试用到的（工单 #434）。 */
const MAX_SCENARIO_NO = 19;

/** 回放时每一步之间推进的毫秒数：事件之间留出动作演完的间隔，其余调用之间只推进一帧。 */
const GAP_MS = { event: 900, other: 50 };

/** 全部事件播完以后静置多久再取最后一个检查点：时间线放空（原型 checks/replay.js 的 SETTLE）。 */
const SETTLE_MS = 14000;

// 在页面里运行的录制驱动：包装 createFloorScene 与翻译层，记录画面收到的状态、实时内容与页面收到的事件。
const DRIVER = () => {
  const Y = window.Y13;
  const P = Y.pixel;
  const T = Y.translate;
  /** 当前这一段录制的调用；null 时什么都不记（两次播放之间）。 */
  let ops = [];
  const push = (op, arg, extra) => {
    if (!ops) return;
    ops.push(Object.assign({ op }, extra ?? {}, { arg: arg === undefined ? null : JSON.parse(JSON.stringify(arg)) }));
  };

  const create = P.createFloorScene;
  P.createFloorScene = function wrapped(canvas, opts) {
    const obj = create.call(this, canvas, opts);
    push("mount");
    // 状态：jump 清空时间线直接显示，setState 等它之前的动作演完（画面合同的两个入口）
    const jump = obj.jump;
    obj.jump = function () { push("state", arguments[0], { jump: true }); return jump.apply(this, arguments); };
    const setState = obj.setState;
    obj.setState = function () { push("state", arguments[0], { jump: false }); return setState.apply(this, arguments); };
    // 实时内容：决定卡片的列表、覆盖层、聚焦的事项
    const setDecisions = obj.setDecisions;
    obj.setDecisions = function () { push("decisions", arguments[0]); return setDecisions.apply(this, arguments); };
    const setOverlay = obj.setOverlay;
    obj.setOverlay = function (id) { push("overlay", { id: id ?? null, data: arguments[1] ?? null }); return setOverlay.apply(this, arguments); };
    const focus = obj.focus;
    obj.focus = function (id) { push("focus", id ?? null); return focus.apply(this, arguments); };
    return obj;
  };

  // 一条事件：页面的 play(ev) 先交给 T.stream（流式文字），再交给 T.floor.actions（动作）。
  // 在 actions 上记下原始事件，回放时两边的翻译层各翻一次
  const actions = T.floor.actions;
  T.floor.actions = function () { push("event", arguments[0]); return actions.apply(this, arguments); };

  return {
    /** 播放一个场景，返回录下的调用。 */
    play: async (id, pid) => {
      const app = window.Y13;
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const overview = "#/p/" + pid + "/overview";
      ops = [];
      app.scenario.select(id);
      await sleep(350);
      if (location.hash !== overview) app.go(overview);
      await sleep(600);
      const total = app.scenario.current().steps.length;
      let guard = 0;
      while (app.scenario.state().step < total && guard++ < 90) {
        app.scenario.step();
        await sleep(420);
        if (location.hash !== overview) {
          app.go(overview);
          await sleep(400);
        }
      }
      await sleep(600);
      const out = ops;
      ops = null;
      return out;
    },
  };
};

async function main() {
  const browser = await chromium.launch({ executablePath: EXE });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript(() => sessionStorage.setItem("y13.level", JSON.stringify("S5")));
  await page.goto(ROOT + "#/sys/machines");
  await page.waitForTimeout(700);
  await page.evaluate((src) => { window.__floorRecord = (0, eval)(`(${src})`); }, DRIVER.toString());
  await page.evaluate(() => { window.__floor = window.__floorRecord(); });

  const scenarios = await page.evaluate((maxScenarioNo) => window.Y13.backend.scenarios()
    .filter((s) => s.no <= maxScenarioNo)
    .map((s) => {
      const m = /^#\/p\/([^/]+)\//.exec(s.go || "");
      let pid = m ? m[1] : null;
      if (!pid) pid = s.steps.map((st) => st.event && st.event.project_id).find(Boolean) || null;
      return { id: s.id, name: s.name, level: s.level, pid, steps: s.steps.length };
    }), MAX_SCENARIO_NO);

  const recordings = [];
  for (const sc of scenarios) {
    if (!sc.pid) {
      console.log("跳过（没有项目）", sc.id);
      continue;
    }
    const ops = await page.evaluate(({ id, pid }) => window.__floor.play(id, pid), { id: sc.id, pid: sc.pid });
    recordings.push({ id: sc.id, name: sc.name, level: sc.level, project: sc.pid, ops });
    const counts = ops.reduce((m, o) => { m[o.op] = (m[o.op] || 0) + 1; return m; }, {});
    console.log(sc.id, sc.pid, JSON.stringify(counts));
  }
  await browser.close();
  if (errors.length) console.log("原型页面控制台错误", errors.length, errors.slice(0, 3));

  const payload = {
    generatedFrom: "docs/prototypes/v13（原型 v13 的页面与翻译层，checks/record.js 的做法；工单 #957）",
    gapMs: GAP_MS,
    settleMs: SETTLE_MS,
    scenarios: recordings,
  };
  mkdirSync(outDir, { recursive: true });
  if (!WRITE) {
    if (!existsSync(outFile)) {
      throw new Error(`没有录下的调用记录：${outFile}；用 --write 生成`);
    }
    // 换行符由 git 按平台转换：比较之前先归一成 \n
    const before = readFileSync(outFile, "utf8").replace(/\r\n/g, "\n");
    const after = JSON.stringify(payload) + "\n";
    if (before !== after) {
      throw new Error("录下的调用与原记录不同；确认以后用 --write 重写");
    }
    console.log("录下的调用与原记录相同：", outFile);
    return;
  }
  writeFileSync(outFile, JSON.stringify(payload) + "\n", "utf8");
  console.log("写入", outFile, recordings.length, "个场景", "控制台错误", errors.length);
}

await main();
