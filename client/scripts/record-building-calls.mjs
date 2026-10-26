// 首页楼的调用录制（工单 #957；原型 v13 的页面与翻译层，做法照 docs/prototypes/v13/checks/record.js）：
// 在 v13 的页面上播放 sc-return-home（离开三天后回来），录下首页的楼（createBuildingScene）收到的状态
// 与页面收到的事件。
//
// 录的是 Yudao 的说法：状态是 v13 的翻译层从 projects.list 与各项目的 project.loop 翻好、交给画面的画面合同状态，
// 事件是页面收到的原始事件（带位置）。回放时客户端的事件由客户端的翻译层翻成动作。
//
// 每段录制要在回放时比的是最后一个检查点：事件播完、时间线放空以后，与 v13 的画面逐像素、逐个小人相同，
// 所以录制里只存调用，不存状态与截图；比较在 tests/helpers/building-replay.ts 里做。
//
// 录下的调用序列存入客户端的测试目录（tests/fixtures/building/recordings.json），
// 只经重写开关更新（--write 时才写；否则只比较，不一致时报错）。
//
// 用法：node client/scripts/record-building-calls.mjs [--write]
// 需要 Playwright 的 Chromium（PLAYWRIGHT_PATH 可以指定位置，CHROMIUM_EXE 指定可执行文件）。

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..");
const repoRoot = resolve(clientRoot, "..");
const outDir = join(clientRoot, "tests", "fixtures", "building");
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

/** 录下的场景：离开三天后回来，走首页的楼（动作由回放驱动 setModel 与 playEvent 的地方）。 */
const SCENARIO_ID = "sc-return-home";

/** 回放时每一步之间推进的毫秒数：事件之间留出动作演完的间隔，其余调用之间只推进一帧。 */
const GAP_MS = { event: 900, other: 50 };

/** 全部事件播完以后静置多久再取最后一个检查点：时间线放空（原型 checks/replay.js 的 SETTLE）。 */
const SETTLE_MS = 14000;

// 在页面里运行的录制驱动：包装 createBuildingScene 与翻译层，记录楼收到的状态与页面收到的事件。
const DRIVER = () => {
  const Y = window.Y13;
  const P = Y.pixel;
  const T = Y.translate;
  /** 当前这一段录制的调用；null 时什么都不记。 */
  let ops = [];
  const push = (op, arg, extra) => {
    if (!ops) return;
    ops.push(Object.assign({ op }, extra ?? {}, { arg: arg === undefined ? null : JSON.parse(JSON.stringify(arg)) }));
  };

  const create = P.createBuildingScene;
  P.createBuildingScene = function wrapped(canvas, opts) {
    const obj = create.call(this, canvas, opts);
    push("mount");
    const jump = obj.jump;
    obj.jump = function () { push("state", arguments[0], { jump: true }); return jump.apply(this, arguments); };
    const setState = obj.setState;
    obj.setState = function () { push("state", arguments[0], { jump: false }); return setState.apply(this, arguments); };
    return obj;
  };

  // 一条事件：页面的 onEvent 交给 T.building.actions（动作）。在它上面记下原始事件，回放时两边的翻译层各翻一次
  const actions = T.building.actions;
  T.building.actions = function () { push("event", arguments[0]); return actions.apply(this, arguments); };

  return {
    /** 播放离开三天后回来，返回录下的调用。 */
    play: async (id) => {
      const app = window.Y13;
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      ops = [];
      app.scenario.select(id);
      await sleep(350);
      app.go("#/home");
      await sleep(700);
      const total = app.scenario.current().steps.length;
      let guard = 0;
      while (app.scenario.state().step < total && guard++ < 90) {
        app.scenario.step();
        await sleep(420);
        if (location.hash !== "#/home") {
          app.go("#/home");
          await sleep(400);
        }
      }
      await sleep(700);
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
  await page.evaluate((src) => { window.__buildingRecord = (0, eval)(`(${src})`); }, DRIVER.toString());
  await page.evaluate(() => { window.__building = window.__buildingRecord(); });
  const meta = await page.evaluate((id) => {
    const s = window.Y13.backend.scenarios().find((x) => x.id === id);
    return s ? { id: s.id, name: s.name, level: s.level } : null;
  }, SCENARIO_ID);
  if (!meta) throw new Error(`原型场景里没有 ${SCENARIO_ID}`);
  const ops = await page.evaluate((id) => window.__building.play(id), SCENARIO_ID);
  await browser.close();
  if (errors.length) console.log("原型页面控制台错误", errors.length, errors.slice(0, 3));

  const payload = {
    generatedFrom: "docs/prototypes/v13（原型 v13 的页面与翻译层，checks/record.js 的做法；工单 #957）",
    gapMs: GAP_MS,
    settleMs: SETTLE_MS,
    scenarios: [{ id: meta.id, name: meta.name, level: meta.level, ops }],
  };
  mkdirSync(outDir, { recursive: true });
  if (!WRITE) {
    if (!existsSync(outFile)) throw new Error(`没有录下的调用记录：${outFile}；用 --write 生成`);
    // 换行符由 git 按平台转换：比较之前先归一成 \n
    const before = readFileSync(outFile, "utf8").replace(/\r\n/g, "\n");
    const after = JSON.stringify(payload) + "\n";
    if (before !== after) throw new Error("录下的调用与原记录不同；确认以后用 --write 重写");
    console.log("录下的调用与原记录相同：", outFile);
    return;
  }
  writeFileSync(outFile, JSON.stringify(payload) + "\n", "utf8");
  const counts = ops.reduce((m, o) => { m[o.op] = (m[o.op] || 0) + 1; return m; }, {});
  console.log("写入", outFile, JSON.stringify(counts), "控制台错误", errors.length);
}

await main();
