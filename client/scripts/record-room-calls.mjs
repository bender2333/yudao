// 部门房间的调用录制（工单 #177 验收标准 2）：在原型 v10 的页面上播放 19 个场景，
// 依次打开产品的部门工作间，录下部门房间画面收到的 setModel、playEvent 调用，
// 并记录每个事件之后固定时刻的状态：每个角色的任务与姿势、头顶的话、房间状态、管道口状态与信号。
//
// 录下的调用与状态记录存入客户端的测试目录（tests/fixtures/room/recordings.json），
// 只经重写开关更新（--write 时才写；否则只比较，不一致时报错）。
//
// 用法：node client/scripts/record-room-calls.mjs [--write] [--root <原型 index.html 的地址>]
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

const args = process.argv.slice(2);
const WRITE = args.includes("--write");
const rootArg = args.indexOf("--root");
const ROOT = rootArg >= 0 ? args[rootArg + 1] : pathToFileURL(join(repoRoot, "docs", "prototypes", "v10", "index.html")).href;

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

/** 录下的场景编号上限：编号 20、21 是自举试点的场景，由实现覆盖层的工单加入录制（工单 #434）。 */
const MAX_SCENARIO_NO = 19;

/** 每个事件之后固定的时刻：取 5000 毫秒，抓动作收尾之后的稳定状态。 */
const SAMPLE_MS = [5000];

// 在页面里运行的录制驱动：包装 createRoomScene，记录调用；在每次调用之后把时钟推进到固定时刻并取状态。
const DRIVER = async ({ sampleMs, departments }) => {
  const P = window.Y10.pixel;
  // 确定的时钟：rAF 的回调收进队列，由 step 按固定步长推进
  let t = 0;
  const q = [];
  window.requestAnimationFrame = (cb) => { q.push(cb); return q.length; };
  window.cancelAnimationFrame = () => {};
  performance.now = () => t;
  // 确定的随机数：待机伸懒腰与打字停顿的时机由它决定，客户端回放用同一个生成器
  let seed = 987654321;
  const resetRandom = () => { seed = 987654321; };
  Math.random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const step = (ms) => {
    const n = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < n; i++) {
      t += 50;
      const cbs = q.splice(0);
      for (const cb of cbs) cb(t);
    }
  };

  /** 取一份状态：角色、房间状态与管道口。 */
  function snapshot(rm, model) {
    const sc = rm.scene;
    const chars = sc.actors
      .filter((a) => a.data && a.data.role)
      .sort((a, b) => (a.id < b.id ? -1 : 1))
      .map((a) => [
        a.id,
        a.data.role.kind,
        a.data.doing || null,
        a.anim,
        a.icon ? a.icon.kind : null,
        a.data.say ? a.data.say.text : null,
        Math.round(a.x),
        Math.round(a.y),
        Boolean(a.seat),
        a.visible !== false,
        a.seed ?? null,
        a.data.nextStretch ?? null,
      ]);
    return {
      chars, status: (model && model.status) || null, door: (model && model.door) || null,
      letters: (model && model.pipes && model.pipes.letters_waiting) || 0, t: Math.round(sc.realT * 100) / 100,
    };
  }

  const orig = P.createRoomScene;
  const out = {};
  for (const dept of departments) out[dept] = { ops: [], samples: [] };
  let currentDept = null;

  P.createRoomScene = function wrapped(canvas, opts) {
    resetRandom();
    const obj = orig.call(this, canvas, opts);
    currentDept = opts.department;
    const rec = out[currentDept];
    rec.ops = [];
    rec.samples = [];
    let model = null;
    const push = (op, arg) => rec.ops.push({ op, arg: arg === undefined ? null : JSON.parse(JSON.stringify(arg)) });
    push("mount", { department: opts.department });
    ["setModel", "playEvent"].forEach((name) => {
      const f = obj[name];
      obj[name] = function () {
        push(name, arguments[0]);
        if (name === "setModel") model = arguments[0];
        const ret = f.apply(this, arguments);
        step(sampleMs[0]);
        rec.samples.push({ after: rec.ops.length - 1, ms: sampleMs[0], state: snapshot(obj, model) });
        return ret;
      };
    });
    const d = obj.destroy;
    obj.destroy = function () { push("destroy"); return d.apply(this, arguments); };
    return obj;
  };

  return {
    play: async (id, pid, dept) => {
      const app = window.Y10;
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      app.scenario.select(id);
      await sleep(250);
      const hash = "#/p/" + pid + "/dept/" + dept;
      if (location.hash !== hash) app.go(hash);
      await sleep(700);
      const total = app.scenario.current().steps.length;
      let guard = 0;
      while (app.scenario.state().step < total && guard++ < 90) {
        app.scenario.step();
        await sleep(420);
        if (!location.hash.startsWith("#/p/" + pid + "/dept/")) {
          app.go(hash);
          await sleep(400);
        }
      }
      await sleep(600);
      return currentDept;
    },
    take: (dept) => out[dept],
  };
};

async function main() {
  const browser = await chromium.launch({ executablePath: EXE });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript(() => sessionStorage.setItem("y10.level", JSON.stringify("S5")));
  await page.goto(ROOT + "#/sys/machines");
  await page.waitForTimeout(700);
  await page.evaluate((src) => { window.__roomDriver = (0, eval)(`(${src})`); }, DRIVER.toString());
  await page.evaluate(async (departments) => { window.__room = await window.__roomDriver({ sampleMs: [5000], departments }); }, DEPARTMENTS);

  // 只录现有测试用到的场景（编号 1 至 19）：编号 20、21 是自举试点的场景，由实现覆盖层的工单加入录制
  const scenarios = await page.evaluate((maxScenarioNo) => window.Y10.backend.scenarios().filter((s) => s.no <= maxScenarioNo).map((s) => {
    const m = /^#\/p\/([^/]+)\//.exec(s.go || "");
    let pid = m ? m[1] : null;
    if (!pid) pid = s.steps.map((st) => st.event && st.event.project_id).find(Boolean) || null;
    return { id: s.id, name: s.name, pid };
  }), MAX_SCENARIO_NO);

  const recordings = [];
  for (const sc of scenarios) {
    if (!sc.pid) {
      console.log("跳过（没有项目）", sc.id);
      continue;
    }
    for (const dept of DEPARTMENTS) {
      const rec = await page.evaluate(({ id, pid, dept }) => window.__room.play(id, pid, dept).then(() => window.__room.take(dept)), { id: sc.id, pid: sc.pid, dept });
      if (rec.ops.length <= 1) continue;
      recordings.push({ id: `${sc.id}__${dept}`, name: sc.name, department: dept, project: sc.pid, ops: rec.ops, samples: rec.samples });
      console.log(sc.id, dept, "调用", rec.ops.length, "样本", rec.samples.length);
    }
  }
  await browser.close();
  if (errors.length) console.log("原型页面控制台错误", errors.length, errors.slice(0, 3));
  const payload = {
    generatedFrom: "docs/prototypes/v10（部门房间，工单 #177）",
    sampleMs: SAMPLE_MS,
    scenarios: recordings,
  };
  mkdirSync(outDir, { recursive: true });
  if (!WRITE) {
    if (!existsSync(outFile)) throw new Error(`没有录下的调用记录：${outFile}；用 --write 生成`);
    const before = readFileSync(outFile, "utf8");
    const after = JSON.stringify(payload) + "\n";
    if (before !== after) throw new Error("录下的调用与原记录不同；确认以后用 --write 重写");
    console.log("录下的调用与原记录相同：", outFile);
    return;
  }
  writeFileSync(outFile, JSON.stringify(payload) + "\n", "utf8");
  console.log("写入", outFile, recordings.length, "份录制", "控制台错误", errors.length);
}

await main();
