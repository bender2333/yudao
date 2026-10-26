// 部门房间的调用录制（工单 #1069；原型 v13 的页面与翻译层，做法照 docs/prototypes/v13/checks/record.js 与
// client/scripts/record-floor-calls.mjs）：在 v13 的页面上逐个播放场景，依次打开三个部门的部门工作间，
// 录下部门房间画面收到的查询结果与页面收到的事件。
//
// 录的是 Yudao 的说法：查询结果是 department.workspace 结果里房间的那一块（带快照位置），事件是页面收到的
// 原始事件（工具名已经是 bash）。回放时两边的翻译层各翻一次：位置的写法、状态词与动作交给画面
// （tests/helpers/room-replay.ts）。
//
// 每段录制要在回放时比的是最后一个检查点：事件播完、时间线放空以后，与 v13 的画面逐像素、逐个小人相同，
// 所以录制里只存调用，不存状态与截图；比较在 tests/helpers/room-replay.ts 里做。
//
// 只录 room 那一块：department.workspace 的结果还有事项、消息、指导与上下文快照，房间画面一个都不读
// （原型 js/translate/translate.js 的 T.room.state 只取 workspace.room），去掉以后录制小得多。
// 与真实接口对不上的数据：设计说明第 8 节说的是 v13 的楼层查询（project.loop）里的事项 title 与
// stamp、覆盖层、来源；房间这一块与真实接口的 RoomView（harness/app/project_queries.py）字段一致，
// 没有要去掉的。
//
// 为什么改（工单 #1069 第 1 步，录制脚本卡住）：#957 那一轮 19 个场景 × 3 个部门跑了 30 分钟没有一行输出、
// 进程 CPU 空转。查到的两处会让它看起来卡住的原因都在这个脚本里：
//   1. 浏览器路径写死成另一个用户的目录（C:/Users/BA_H3C_Pad/...），在别的机器上 launch 直接失败；
//      现在默认用装好的 Playwright 浏览器，CHROMIUM_EXE 只在要指定时才设。
//   2. 每次播放只在**整段跑完以后**才打印一行，播放期间没有任何输出；而 page.evaluate 里的播放一旦等不到
//      页面推进（守卫循环每轮 420 毫秒，最多 90 轮），整段最长要 38 秒，57 段合计可以超过 30 分钟，
//      这期间屏幕上什么都没有。现在每段开播前先打印一行（卡住时看得到是哪一段），并给每段加超时：
//      超时报出这一段的名字与最后录到的一条调用，不再空转到天荒地老。
//
// 录下的调用序列存入客户端的测试目录（tests/fixtures/room/recordings.json），
// 只经重写开关更新（--write 时才写；否则只比较，不一致时报错）。
//
// 用法：node client/scripts/record-room-calls.mjs [--write]
// 需要 Playwright 的 Chromium（PLAYWRIGHT_PATH 指定 Playwright 模块，CHROMIUM_EXE 指定可执行文件）。

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
const argOf = (name, dflt) => { const i = args.indexOf("--" + name); return i >= 0 ? args[i + 1] : dflt; };
/** 只录一部分时用：--dept product --only sc-todo-loop（查录制脚本本身的问题时用，不带时录全部）。 */
const ONLY_DEPT = argOf("dept", null);
const ONLY_SCENARIO = argOf("only", null);

const playwrightPath = process.env.PLAYWRIGHT_PATH
  || join(repoRoot, ".tmp", "v8", "pw", "node_modules", "playwright");
let chromium;
if (existsSync(playwrightPath)) {
  chromium = require(playwrightPath).chromium;
} else {
  ({ chromium } = await import("@playwright/test"));
}

/** 录下的部门：产品房间接收与项目全局有关的事件（交接、传信、提案、状态），最能反映房间的行为。 */
const ALL_DEPARTMENTS = ["product", "engineering", "quality"];
const DEPARTMENTS = ONLY_DEPT ? [ONLY_DEPT] : ALL_DEPARTMENTS;

/** 场景编号上限：编号 20 以上的场景是自举试点与新画面的，只录现有测试用到的（工单 #434）。 */
const MAX_SCENARIO_NO = 19;

/** 回放时每一步之间推进的毫秒数：事件之间留出动作演完的间隔，其余调用之间只推进一帧。 */
const GAP_MS = { event: 900, other: 50 };

/** 全部事件播完以后静置多久再取最后一个检查点：时间线放空（原型 checks/replay.js 的 SETTLE）。 */
const SETTLE_MS = 14000;

/** 一段播放最多等多久：守卫循环每轮 420 毫秒、最多 90 轮，再加开播前的几次等待，都不该超过一分钟。 */
const PLAY_TIMEOUT_MS = 120000;

// 在页面里运行的录制驱动：包装 createRoomScene 与翻译层，记录房间画面收到的查询结果与页面收到的事件。
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

  // 房间的状态来自 department.workspace（带快照位置）：记下它的输入，画面上什么时候上由 jump / setState 决定
  let pending = null;
  const state = T.room.state;
  T.room.state = function (o) {
    pending = { position: o?.position ?? 0, workspace: o?.workspace ?? null };
    return state.apply(this, arguments);
  };

  const create = P.createRoomScene;
  P.createRoomScene = function wrapped(canvas, opts) {
    const obj = create.call(this, canvas, opts);
    push("mount", { department: opts && opts.department ? opts.department : null });
    const jump = obj.jump;
    obj.jump = function () {
      push("workspace", pending ? pending.workspace : null, { jump: true, position: pending ? pending.position : 0 });
      return jump.apply(this, arguments);
    };
    const setState = obj.setState;
    obj.setState = function () {
      push("workspace", pending ? pending.workspace : null, { jump: false, position: pending ? pending.position : 0 });
      return setState.apply(this, arguments);
    };
    return obj;
  };

  // 一条事件：页面的 onEvent 先交给 T.stream（流式文字），再交给 T.room.actions（动作）。
  // 在 actions 上记下原始事件，回放时两边的翻译层各翻一次
  const actions = T.room.actions;
  T.room.actions = function () { push("event", arguments[0]); return actions.apply(this, arguments); };

  return {
    /** 播放一个场景并打开这个部门的房间，返回录下的调用。 */
    play: async (id, pid, dept) => {
      const app = window.Y13;
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const hash = "#/p/" + pid + "/dept/" + dept;
      ops = [];
      app.scenario.select(id);
      await sleep(250);
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
      const out = ops;
      ops = null;
      return out;
    },
    /** 这一段最后录到的一条调用：卡住或超时时用来报出卡在哪一步。 */
    last: () => (ops && ops.length ? ops[ops.length - 1] : null),
  };
};

/** room 那一块：房间画面唯一读的那部分（原型 T.room.state 只取 workspace.room）。 */
const roomPartOf = (workspace) => {
  if (!workspace || typeof workspace !== "object") return null;
  const room = workspace.room;
  return room && typeof room === "object" ? { room } : null;
};

async function main() {
  const browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
  try {
    await record(browser);
  } finally {
    // 卡住或报错也要关掉浏览器，不留一个空转的进程
    await browser.close().catch(() => {});
  }
}

async function record(browser) {
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
    if (ONLY_SCENARIO && sc.id !== ONLY_SCENARIO) continue;
    if (!sc.pid) {
      console.log("跳过（没有项目）", sc.id);
      continue;
    }
    for (const dept of DEPARTMENTS) {
      // 开播前先打印：卡住时看得到卡在哪一段（工单 #1069 第 1 步）
      process.stdout.write(`录制 ${sc.id} ${dept} … `);
      const started = Date.now();
      const play = page.evaluate(({ id, pid, department }) => window.__room.play(id, pid, department), { id: sc.id, pid: sc.pid, department: dept });
      const timeout = new Promise((resolvePromise) => setTimeout(() => resolvePromise("timeout"), PLAY_TIMEOUT_MS));
      const outcome = await Promise.race([play.then((ops) => ({ ops })), timeout]);
      if (outcome === "timeout") {
        const last = await page.evaluate(() => window.__room.last()).catch(() => null);
        throw new Error(`录制卡住：${sc.id} ${dept} 超过 ${PLAY_TIMEOUT_MS} 毫秒没有播完；最后录到的一条调用是 ${JSON.stringify(last)}`);
      }
      const ops = outcome.ops
        // 查询结果只留 room 那一块（见文件开头的说明）
        .map((op) => (op.op === "workspace" ? { ...op, arg: roomPartOf(op.arg) } : op));
      // 只有房间画面挂上过（有 workspace 或事件）才留一份录制
      if (!ops.some((o) => o.op === "workspace" || o.op === "event")) { console.log("跳过（房间没有挂上）"); continue; }
      recordings.push({ id: `${sc.id}__${dept}`, name: sc.name, level: sc.level, department: dept, project: sc.pid, ops });
      const counts = ops.reduce((m, o) => { m[o.op] = (m[o.op] || 0) + 1; return m; }, {});
      console.log(JSON.stringify(counts), `${((Date.now() - started) / 1000).toFixed(1)} 秒`);
    }
  }
  if (errors.length) console.log("原型页面控制台错误", errors.length, errors.slice(0, 3));

  const payload = {
    generatedFrom: "docs/prototypes/v13（原型 v13 的页面与翻译层，checks/record.js 的做法；工单 #1069）",
    gapMs: GAP_MS,
    settleMs: SETTLE_MS,
    scenarios: recordings,
  };
  if (ONLY_DEPT || ONLY_SCENARIO) {
    console.log("只录了一部分（--dept/--only），不写入录制文件：", recordings.length, "份录制");
    return;
  }
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
