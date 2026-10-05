// 首页楼的调用录制（工单 #178 验收标准 2）：在原型 v9 的页面上播放 sc-return-home（离开三天后回来），
// 录下首页的楼（createBuildingScene）收到的 setModel、playEvent、destroy 调用（与 #82 的 record-floor-calls.mjs 同一套做法），
// 并记录每个调用之后固定时刻的楼层与小人状态：每层的灯、小旗、阀门、状态灯与决定计数，以及每层小人的位置、姿势与朝向。
//
// 录下的调用序列与状态记录存入客户端的测试目录（tests/fixtures/building/recordings.json），
// 只经重写开关更新（--write 时才写；否则只比较，不一致时报错）。
//
// 用法：node client/scripts/record-building-calls.mjs [--write] [--root <原型 index.html 的地址>]
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

const args = process.argv.slice(2);
const WRITE = args.includes("--write");
const rootArg = args.indexOf("--root");
const ROOT = rootArg >= 0 ? args[rootArg + 1] : pathToFileURL(join(repoRoot, "docs", "prototypes", "v9", "index.html")).href;

const playwrightPath = process.env.PLAYWRIGHT_PATH
  || join(repoRoot, ".tmp", "v8", "pw", "node_modules", "playwright");
let chromium;
if (existsSync(playwrightPath)) {
  chromium = require(playwrightPath).chromium;
} else {
  ({ chromium } = await import("@playwright/test"));
}
const EXE = process.env.CHROMIUM_EXE || "C:/Users/BA_H3C_Pad/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe";

/** 每个调用之后固定的时刻：录下的状态在这些毫秒数上取。 */
const SAMPLE_MS = [5000];

// 在页面里运行的录制驱动：包装 createBuildingScene，记录调用；在每次调用之后把时钟推进到固定时刻并取状态。
const DRIVER = async ({ sampleMs }) => {
  const P = window.Y9.pixel;
  const E = P.ecs;
  // 确定的时钟与随机数（与 #82 的录制裁法一致）
  let t = 0;
  const q = [];
  window.requestAnimationFrame = (cb) => { q.push(cb); return q.length; };
  window.cancelAnimationFrame = () => {};
  performance.now = () => t;
  let seed = 987654321;
  Math.random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  // 楼的画面挂载前把随机数复位到同一个起点：客户端在建立楼画面时也用同一个起点，
  // 两边从小人的第一趟走位起消耗同一串随机数，位置才可对照
  window.__resetSeed = () => { seed = 987654321; };
  const step = (ms) => {
    const n = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < n; i++) {
      t += 50;
      const cbs = q.splice(0);
      for (const cb of cbs) cb(t);
    }
  };
  // 录制时关掉自主行为：静止的画面只由快照决定
  E.config.autonomy = false;

  /** 取一份状态：每层的灯、小旗、阀门、状态灯与决定计数，以及每层小人的位置、姿势与朝向。 */
  function snapshot(b) {
    const ins = b.inspect();
    const world = ins.world;
    const scene = b.scene;
    const floors = (ins.model.floors || []).map((f) => [
      f.project_id,
      f.status,
      [f.lit && f.lit.product ? 1 : 0, f.lit && f.lit.engineering ? 1 : 0, f.lit && f.lit.quality ? 1 : 0, f.lit && f.lit.operations ? 1 : 0],
      (f.flags || []).map((fl) => [fl.work_item_id, fl.department, fl.color_index]),
      f.valve_closed ? 1 : 0,
      f.decisions,
    ]);
    const walkers = Object.keys(world.characters).sort().map((id) => {
      const a = scene.actors.find((x) => x.id === "ch-" + id);
      return [id, a ? Math.round(a.x) : null, a ? Math.round(a.y) : null, a ? a.anim : null, a ? a.speed : null, a ? a.facing : null];
    });
    return { floors, walkers };
  }

  const orig = P.createBuildingScene;
  const recordings = [];
  let current = null;

  P.createBuildingScene = function wrapped(canvas, opts) {
    // 楼的画面挂载时把随机数复位到同一个起点：客户端在建立楼画面时也用同一个起点，
    // 两边从小人的第一趟走位起消耗同一串随机数，位置才可对照
    window.__resetSeed();
    const obj = orig.call(this, canvas, opts);
    const rec = { ops: [], samples: [] };
    current = rec;
    const push = (op, arg) => {
      rec.ops.push({ op, arg: arg === undefined ? null : JSON.parse(JSON.stringify(arg)) });
    };
    push("mount");
    ["setModel", "playEvent"].forEach((name) => {
      const f = obj[name];
      obj[name] = function () {
        push(name, arguments[0]);
        const out = f.apply(this, arguments);
        for (const ms of sampleMs) {
          step(ms);
          rec.samples.push({ after: rec.ops.length - 1, ms, state: snapshot(obj) });
        }
        return out;
      };
    });
    const destroy = obj.destroy;
    obj.destroy = function () {
      push("destroy");
      return destroy.apply(this, arguments);
    };
    return obj;
  };

  // 播放 sc-return-home：它只走首页，动作是 replay.start/step/live，会驱动楼的 setModel 与 playEvent
  window.__playReturnHome = async (id) => {
    const app = window.Y9;
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
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
    return current;
  };

  return window.Y9.backend.scenarios().map((s) => ({ id: s.id, name: s.name, level: s.level, go: s.go || null }));
};

/** 楼层里客户端画面用到的字段：与 scenes.js 的 buildingModels 一致。 */
function trimFloor(f) {
  return {
    project_id: f.project_id, name: f.name, status: f.status,
    lit: f.lit, has_ops: Boolean(f.has_ops), flags: f.flags ?? [],
    valve_closed: Boolean(f.valve_closed), machine_ids: f.machine_ids ?? [], link_active: Boolean(f.link_active),
    decisions: f.decisions ?? 0,
  };
}

async function main() {
  const browser = await chromium.launch({ executablePath: EXE });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript(() => {
    sessionStorage.setItem("y9.level", JSON.stringify("S5"));
    // 页面加载前就把随机数换成确定的序列：原型的卡片动画等也会取随机数，只有全程确定，
    // 客户端用同一套序列回放时小人的走位才可对照
    let seed = 987654321;
    Math.random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  });
  await page.goto(ROOT + "#/sys/machines");
  await page.waitForTimeout(700);
  const scenarios = await page.evaluate(DRIVER, { sampleMs: SAMPLE_MS });
  const target = scenarios.find((s) => s.id === "sc-return-home");
  if (!target) throw new Error("原型场景里没有 sc-return-home");
  const rec = await page.evaluate((id) => window.__playReturnHome(id), target.id);
  await browser.close();
  if (errors.length) {
    console.log("原型页面控制台错误", errors.length, errors.slice(0, 3));
  }
  // setModel 的模型放进共享的表，调用里只留索引：同一个模型只存一份
  const models = [];
  const modelIndex = new Map();
  rec.ops = rec.ops.map((op) => {
    if (op.op !== "setModel") return op;
    const trimmed = { floors: (op.arg.floors ?? []).map(trimFloor), show_basement: Boolean(op.arg.show_basement) };
    const text = JSON.stringify(trimmed);
    if (!modelIndex.has(text)) {
      modelIndex.set(text, models.length);
      models.push(trimmed);
    }
    return { op: op.op, model: modelIndex.get(text) };
  });
  const payload = {
    generatedFrom: "docs/prototypes/v9（原型 scenes.js 的 buildingModels 与 checks/record.js 的做法）",
    sampleMs: SAMPLE_MS,
    models,
    scenarios: [{ id: target.id, name: target.name, level: target.level, ops: rec.ops, samples: rec.samples }],
  };
  mkdirSync(outDir, { recursive: true });
  if (!WRITE) {
    if (!existsSync(outFile)) {
      throw new Error(`没有录下的调用记录：${outFile}；用 --write 生成`);
    }
    const before = readFileSync(outFile, "utf8");
    const after = JSON.stringify(payload) + "\n";
    if (before !== after) {
      throw new Error("录下的调用与原记录不同；确认以后用 --write 重写");
    }
    console.log("录下的调用与原记录相同：", outFile);
    return;
  }
  writeFileSync(outFile, JSON.stringify(payload) + "\n", "utf8");
  console.log("写入", outFile, "调用", rec.ops.length, "样本", rec.samples.length, "控制台错误", errors.length);
}

await main();
