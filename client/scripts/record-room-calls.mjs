// 部门房间的调用录制（工单 #957；原型 v13 的页面与翻译层，做法照 docs/prototypes/v13/checks/record.js）：
// 在 v13 的页面上逐个播放场景，依次打开三个部门的部门工作间，录下部门房间画面收到的查询结果与页面收到的事件。
//
// 录的是 Yudao 的说法：查询结果是 department.workspace 的结果（带快照位置），事件是页面收到的原始事件
// （工具名已经是 bash）。回放时两边的翻译层各翻一次：位置的写法、状态词与动作交给画面。
//
// 每段录制要在回放时比的是最后一个检查点：事件播完、时间线放空以后，与 v13 的画面逐像素、逐个小人相同，
// 所以录制里只存调用，不存状态与截图；比较在 tests/helpers/room-replay.ts 里做。
//
// 录下的调用序列存入客户端的测试目录（tests/fixtures/room/recordings.json），
// 只经重写开关更新（--write 时才写；否则只比较，不一致时报错）。
//
// 用法：node client/scripts/record-room-calls.mjs [--write]
// 需要 Playwright 的 Chromium（PLAYWRIGHT_PATH 可以指定位置，CHROMIUM_EXE 指定可执行文件）。

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..");
const repoRoot = resolve(clientRoot, "..");
const outDir = join(clientRoot, "tests", "fixtures", "room");
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

/** 录下的部门：产品房间接收与项目全局有关的事件（交接、传信、提案、状态），最能反映房间的行为。 */
const DEPARTMENTS = ["product", "engineering", "quality"];

/** 场景编号上限：编号 20 以上的场景是自举试点与新画面的，只录现有测试用到的（工单 #434）。 */
const MAX_SCENARIO_NO = 19;

/** 回放时每一步之间推进的毫秒数：事件之间留出动作演完的间隔，其余调用之间只推进一帧。 */
const GAP_MS = { event: 900, other: 50 };

/** 全部事件播完以后静置多久再取最后一个检查点：时间线放空（原型 checks/replay.js 的 SETTLE）。 */
const SETTLE_MS = 14000;

// 在页面里运行的录制驱动：包装 createRoomScene 与翻译层，记录房间画面收到的查询结果与页面收到的事件。
const DRIVER = () => {
  const Y = window.Y13;
  const P = Y.pixel;
  const T = Y.translate;
  let targetDept = null;
  /** 当前这一段录制的调用；null 时什么都不记。 */
  let ops = [];
  const push = (op, arg, extra) => {
    if (!ops || !targetDept) return;
    ops.push(Object.assign({ op }, extra ?? {}, { arg: arg === undefined ? null : JSON.parse(JSON.stringify(arg)) }));
  };

  // 房间的状态来自 department.workspace（带快照位置）：按部门记下它的输入，画面上什么时候上由 jump / setState 决定
  const pendingByDept = {};
  const state = T.room.state;
  T.room.state = function (o) {
    const d = o?.workspace?.room?.department;
    if (d) pendingByDept[d] = { position: o?.position ?? 0, workspace: o?.workspace ?? null };
    return state.apply(this, arguments);
  };

  const create = P.createRoomScene;
  P.createRoomScene = function wrapped(canvas, opts) {
    const obj = create.call(this, canvas, opts);
    const d = opts && opts.department;
    if (d !== targetDept) return obj;
    push("mount", { department: d });
    const jump = obj.jump;
    obj.jump = function () {
      const p = pendingByDept[d];
      push("workspace", p ? p.workspace : null, { jump: true, position: p ? p.position : 0 });
      return jump.apply(this, arguments);
    };
    const setState = obj.setState;
    obj.setState = function () {
      const p = pendingByDept[d];
      push("workspace", p ? p.workspace : null, { jump: false, position: p ? p.position : 0 });
      return setState.apply(this, arguments);
    };
    return obj;
  };

  // 一条事件：页面的 onEvent 先交给 T.stream（流式文字），再交给 T.room.actions（动作）。
  // 在 actions 上记下原始事件，回放时两边的翻译层各翻一次
  const actions = T.room.actions;
  T.room.actions = function (ev, dept) {
    if (dept === targetDept) {
      push("event", ev);
    }
    return actions.apply(this, arguments);
  };

  return {
    /** 播放一个场景并打开这个部门的房间，返回录下的调用。 */
    play: async (id, pid, dept) => {
      targetDept = dept;
      const app = window.Y13;
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const hash = "#/p/" + pid + "/dept/" + dept;
      ops = [];
      app.scenario.select(id);
      await sleep(250);
      if (location.hash !== hash) {
        app.go(hash);
        await sleep(700);
      } else {
        await sleep(500);
      }
      const total = app.scenario.current().steps.length;
      let guard = 0;
      while (app.scenario.state().step < total && guard++ < 90) {
        app.scenario.step();
        await sleep(420);
        if (location.hash !== hash) {
          app.go(hash);
          await sleep(400);
        }
      }
      await sleep(600);
      const out = ops;
      ops = null;
      targetDept = null;
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
  await page.evaluate((src) => { window.__roomRecord = (0, eval)(`(${src})`); }, DRIVER.toString());
  await page.evaluate(() => { window.__room = window.__roomRecord(); });

  const scenarios = await page.evaluate((maxScenarioNo) => window.Y13.backend.scenarios()
    .filter((s) => s.no <= maxScenarioNo)
    .map((s) => {
      const m = /^#\/p\/([^/]+)\//.exec(s.go || "");
      let pid = m ? m[1] : null;
      if (!pid) pid = s.steps.map((st) => st.event && st.event.project_id).find(Boolean) || null;
      return { id: s.id, name: s.name, level: s.level, pid };
    }), MAX_SCENARIO_NO);

  const recordings = [];
  for (const sc of scenarios) {
    if (!sc.pid) {
      console.log("跳过（没有项目）", sc.id);
      continue;
    }
    for (const dept of DEPARTMENTS) {
      const ops = await page.evaluate(({ id, pid, department }) => window.__room.play(id, pid, department), { id: sc.id, pid: sc.pid, department: dept });
      // 只有房间画面挂上过（有 workspace 或事件）才留一份录制
      if (!ops.some((o) => o.op === "workspace" || o.op === "event")) continue;
      recordings.push({ id: `${sc.id}__${dept}`, name: sc.name, level: sc.level, department: dept, project: sc.pid, ops });
      const counts = ops.reduce((m, o) => { m[o.op] = (m[o.op] || 0) + 1; return m; }, {});
      console.log(sc.id, dept, JSON.stringify(counts));
    }
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
    if (!existsSync(outFile)) throw new Error(`没有录下的调用记录：${outFile}；用 --write 生成`);
    // 换行符由 git 按平台转换：比较之前先归一成 \n
    const before = readFileSync(outFile, "utf8").replace(/\r\n/g, "\n");
    const after = JSON.stringify(payload) + "\n";
    if (before !== after) throw new Error("录下的调用与原记录不同；确认以后用 --write 重写");
    console.log("录下的调用与原记录相同：", outFile);
    return;
  }
  writeFileSync(outFile, JSON.stringify(payload) + "\n", "utf8");
  console.log("写入", outFile, recordings.length, "份录制", "控制台错误", errors.length);
}

await main();
