// 楼层画面的调用录制（工单 #82 验收标准 2）：在原型 v9 的页面上播放 19 个场景，
// 录下项目楼层画面收到的 setModel、playEvent、focus、setOverlay 调用（原型 checks/record.js 的做法），
// 并记录每个事件之后固定时刻的状态：每个角色的任务、姿势与头顶的话，每个包裹的去向，每根管道的状态与各个信号。
//
// 录下的调用序列与状态记录存入客户端的测试目录（tests/fixtures/floor/recordings.json），
// 只经重写开关更新（--write 时才写；否则只比较，不一致时报错）。
//
// 用法：node client/scripts/record-floor-calls.mjs [--write] [--root <原型 index.html 的地址>]
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

/**
 * 每个事件之后固定的时刻：录下的状态在这些毫秒数上取。
 * 事件进行中的画面（走动、包裹移动、说话气泡）在各版本是同一套结构，取固定的时刻用于逐项对照；
 * 这里取 0 与 800 毫秒两个时刻，短的抓动作的进行中，长的抓动作的收尾。
 */
const SAMPLE_MS = [5000];

// 在页面里运行的录制驱动：包装 createFloorScene，记录调用；在每次调用之后把时钟推进到固定时刻并取状态。
const DRIVER = async ({ sampleMs }) => {
  const P = window.Y9.pixel;
  const E = P.ecs;
  // 确定的时钟与随机数
  let t = 0;
  const q = [];
  window.requestAnimationFrame = (cb) => { q.push(cb); return q.length; };
  window.cancelAnimationFrame = () => {};
  performance.now = () => t;
  let seed = 987654321;
  Math.random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const step = (ms) => {
    const n = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < n; i++) {
      t += 50;
      const cbs = q.splice(0);
      for (const cb of cbs) cb(t);
    }
  };
  // 录制时关掉自主行为：静止的画面只由快照决定，待机活动不影响录下的状态
  E.config.autonomy = false;

  const isWorker = (a) => /\.(agent|ops|manager|architect|lead|explorer|reviewer|tester)$/.test(a.sprite);

  /** 取一份状态：角色、包裹、管道与信号。 */
  function snapshot(fl) {
    const world = fl.inspect().world;
    const scene = fl.scene;
    // 角色：任务、姿势、头顶的话、位置与是否坐在工位（元组形式，减少重复）
    const chars = Object.values(world.characters).sort((a, b) => (a.id < b.id ? -1 : 1)).map((c) => {
      const a = scene.actors.find((x) => x.id === "ch-" + c.id);
      return [
        c.id,
        c.current ? c.current.taskKey : null,
        c.queue.map((x) => x.taskKey),
        a ? a.anim : null,
        a && a.icon ? a.icon.kind : null,
        c.bubble ? c.bubble.text : null,
        a ? Math.round(a.x) : null,
        a ? Math.round(a.y) : null,
        a ? Boolean(a.seat) : null,
        a ? a.visible : null,
      ];
    });
    // 包裹：去向（正在走的管道）与位置（去向是关键，位置取整到像素）
    const packages = Object.values(world.packages).map((pk) => [
      pk.id,
      pk.transit ? pk.transit.linkKey : "rest",
      pk.transit && pk.transit.pos ? [Math.round(pk.transit.pos[0]), Math.round(pk.transit.pos[1])] : null,
    ]).sort((a, b) => (a[0] < b[0] ? -1 : 1));
    // 管道：状态与光点的多少（口径）
    const pipes = Object.keys(world.links).sort().map((key) => [
      key,
      world.links[key].flow ? world.links[key].flow.state : null,
      world.links[key].flow ? Math.round(world.links[key].flow.load * 10) / 10 : null,
    ]);
    const signals = Object.keys(world.signals).sort().filter((name) => world.signals[name].until > scene.realT);
    return { chars, packages, pipes, signals };
  }

  const orig = P.createFloorScene;
  const recordings = [];
  let current = null;

  P.createFloorScene = function wrapped(canvas, opts) {
    const obj = orig.call(this, canvas, opts);
    const rec = { ops: [], samples: [] };
    current = rec;
    const push = (op, arg) => {
      rec.ops.push({ op, arg: arg === undefined ? null : JSON.parse(JSON.stringify(arg)) });
    };
    push("mount");
    ["setModel", "playEvent", "focus"].forEach((name) => {
      const f = obj[name];
      obj[name] = function () {
        push(name, arguments[0]);
        const out = f.apply(this, arguments);
        // 每个事件之后固定时刻的状态：调用之后静置，取几个时刻的状态
        for (const ms of sampleMs) {
          step(ms);
          rec.samples.push({ after: rec.ops.length - 1, ms, state: snapshot(obj) });
        }
        return out;
      };
    });
    const setOverlay = obj.setOverlay;
    obj.setOverlay = function (id, data) {
      push("setOverlay", { id, data });
      return setOverlay.apply(this, arguments);
    };
    const destroy = obj.destroy;
    obj.destroy = function () {
      push("destroy");
      return destroy.apply(this, arguments);
    };
    return obj;
  };

  window.__record = {
    take: () => current,
    stop: () => { P.createFloorScene = orig; },
  };

  /** 播放一个场景，返回录下的调用与状态。 */
  window.__playScenario = async (id, pid) => {
    const app = window.Y9;
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const overview = "#/p/" + pid + "/overview";
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
    return window.__record.take();
  };

  const scenarios = window.Y9.backend.scenarios().map((s) => {
    const m = /^#\/p\/([^/]+)\//.exec(s.go || "");
    let pid = m ? m[1] : null;
    if (!pid) pid = s.steps.map((st) => st.event && st.event.project_id).find(Boolean) || null;
    return { id: s.id, name: s.name, level: s.level, pid, steps: s.steps.length };
  });
  return scenarios;
};

/** 原型 floorModel 里客户端画面用到的字段：事项、角色（去掉模型细节）、决定请求、槽位、运维与机器。 */
function trimModel(model) {
  const roles = {};
  for (const [department, list] of Object.entries(model.roles ?? {})) {
    roles[department] = list.map((r) => ({ id: r.id, name: r.name, kind: r.kind, status: r.status, task: r.task ?? null }));
  }
  return {
    items: model.items ?? [],
    open_requests: model.open_requests ?? [],
    shelves: model.shelves ?? { adopted: [] },
    slots: model.slots ?? null,
    waiting_provider: model.waiting_provider ?? [],
    machines: model.machines ?? null,
    ops: model.ops ?? null,
    interrupted: Boolean(model.interrupted),
    roles,
    decisions: (model.decisions ?? []).map((d) => ({ id: d.id, kind: d.kind, version: d.version, title: d.title, work_item_id: d.work_item_id ?? null })),
  };
}

async function main() {
  const browser = await chromium.launch({ executablePath: EXE });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript(() => sessionStorage.setItem("y9.level", JSON.stringify("S5")));
  await page.goto(ROOT + "#/sys/machines");
  await page.waitForTimeout(700);
  const scenarios = await page.evaluate(DRIVER, { sampleMs: SAMPLE_MS });
  const recordings = [];
  for (const sc of scenarios) {
    if (!sc.pid) {
      console.log("跳过（没有项目）", sc.id);
      continue;
    }
    const rec = await page.evaluate(({ id, pid }) => window.__playScenario(id, pid), { id: sc.id, pid: sc.pid });
    recordings.push({ id: sc.id, name: sc.name, level: sc.level, project: sc.pid, ops: rec.ops, samples: rec.samples });
    console.log(sc.id, sc.pid, "调用", rec.ops.length, "样本", rec.samples.length);
  }
  await browser.close();
  if (errors.length) {
    console.log("原型页面控制台错误", errors.length, errors.slice(0, 3));
  }
  // setModel 的模型放进共享的表，调用里只留索引：同一个模型只存一份。
  // 只留客户端画面用到的字段（原型 models 里的 resolved、rows 等属于卡片内容，不在本项目楼层的范围内）。
  const models = [];
  const modelIndex = new Map();
  for (const rec of recordings) {
    rec.ops = rec.ops.map((op) => {
      if (op.op !== "setModel") return op;
      const trimmed = trimModel(op.arg);
      const text = JSON.stringify(trimmed);
      if (!modelIndex.has(text)) {
        modelIndex.set(text, models.length);
        models.push(trimmed);
      }
      return { op: op.op, model: modelIndex.get(text) };
    });
  }
  const payload = {
    generatedFrom: "docs/prototypes/v9（原型 checks/record.js 的做法）",
    sampleMs: SAMPLE_MS,
    models,
    scenarios: recordings,
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
  console.log("写入", outFile, recordings.length, "个场景", "控制台错误", errors.length);
}

await main();
