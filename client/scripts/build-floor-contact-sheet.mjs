// 楼层画面的过程联系表（工单 #82 验收标准 3，原型 checks/life.js 的做法）：回放录下的调用，
// 在指定事件之后每隔一段时间截一帧，拼成一张联系表，交给用户查看画风与动作。
//
// 录下的调用是原型 v13 的页面上录的（client/scripts/record-floor-calls.mjs，工单 #957）：
// 状态是 v13 的翻译层翻好的画面合同状态，事件是页面收到的原始事件，回放时由客户端的翻译层翻成动作。
//
// 用法：node client/scripts/build-floor-contact-sheet.mjs [--rec 场景编号] [--event 事件类型] [--nth 1] [--frames 12] [--interval 300]
// 输出：client/.tmp/floor-life/floor-<场景>-<事件>-<序号>.png
// 依赖：Playwright 的 Chromium（CHROMIUM_EXE 可以指定位置）。

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import { chromium } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..");
const outDir = join(clientRoot, ".tmp", "floor-life");
mkdirSync(outDir, { recursive: true });

const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : dflt;
};
const REC = arg("rec", "sc-todo-roles");
const EVENT = arg("event", "tool_started");
const NTH = Number(arg("nth", 1));
const FRAMES = Number(arg("frames", 12));
const INTERVAL = Number(arg("interval", 300));
const OUT = arg("out", `floor-${REC}-${EVENT}-${NTH}.png`);

/**
 * v13 的画面合同状态 → 客户端画面合同的状态（与 tests/helpers/floor-replay.ts 的 toViewState 同一件事）：
 * 两边的合同说的是一件事，字段名不同（id、cycle、limit_sec 与 work_item_id、round、time_limit_sec）。
 */
function toViewState(raw) {
  const s = raw ?? {};
  const items = (s.items ?? []).map((it) => ({
    ...it,
    work_item_id: String(it.id ?? ""),
    round: Number(it.cycle ?? 0),
    time_limit_sec: Number(it.limit_sec ?? 0),
    kind: String(it.kind ?? "request"),
    sign: it.sign ?? null,
    department: it.department ?? null,
    color_index: Number(it.color_index ?? 0),
    elapsed_sec: it.elapsed_sec === undefined || it.elapsed_sec === null ? null : Number(it.elapsed_sec),
  }));
  const shelves = s.shelves ?? {};
  return {
    position: Number(s.position ?? 0),
    items,
    open_requests: s.open_requests ?? [],
    shelves: { adopted: shelves.adopted ?? [] },
    slots: s.slots ?? null,
    waiting_provider: s.waiting_provider ?? [],
    machines: s.machines ?? null,
    ops: s.ops ?? null,
    interrupted: Boolean(s.interrupted),
    roles: s.roles ?? null,
    decisions: [],
    ...(s.focus_id ? { focus_id: String(s.focus_id) } : {}),
  };
}

/** 在页面里运行的驱动：回放录下的调用，在指定事件之后每隔一段时间截一帧。 */
async function driver(input) {
  const P = await import("/src/pixel/floor/view.ts");
  const clockMod = await import("/src/pixel/clock.ts");
  const tr = await import("/src/translate/floor.ts");
  // 字段名的换法由外面送进来（与 tests/helpers/floor-replay.ts 的 toViewState 是同一段代码）
  const toView = (0, eval)(`(${input.toViewSource})`);
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:9999;background:#000";
  document.body.appendChild(host);
  const clock = clockMod.createManualClock();
  let view = await P.createFloorView({ host, clock });
  const frames = [];
  let seen = 0;
  const canvas = () => host.querySelector("canvas");
  const shoot = (t, note) => frames.push({ t, note, url: canvas().toDataURL("image/png") });
  const advance = (ms) => {
    const n = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < n; i++) clock.advance(Math.round(clock.now()) + 50);
  };
  let roles = [];
  const roleName = (id) => {
    const hit = roles.find((r) => r.id === id || r.kind === id);
    return hit ? hit.name : null;
  };
  /** 播放一个事件：流式文字与动作都经客户端的翻译层。 */
  const playEvent = (raw) => {
    const ev = {
      type: String(raw.type ?? ""), position: Number(raw.position ?? 0),
      event_id: raw.event_id ?? null, project_id: raw.project_id ?? null, department: raw.department ?? null,
      role: raw.role ?? null, tool: raw.tool ?? null, label: raw.label ?? null,
      work_item_id: raw.work_item_id ?? null, payload: raw.payload ?? null,
    };
    const stream = tr.streamText(ev);
    if (stream) view.stream({ room: stream.room, role: stream.role }, stream.text);
    for (const action of tr.floorActions(ev, { roleName })) view.play(action);
  };
  for (const op of input.ops) {
    if (op.op === "mount") {
      view.destroy();
      view = await P.createFloorView({ host, clock });
      advance(input.gapMs.other);
      continue;
    }
    if (op.op === "state") {
      roles = Object.values(op.arg?.roles ?? {}).reduce((list, x) => list.concat(x ?? []), []);
      if (op.jump) view.jump(toView(op.arg));
      else view.setState(toView(op.arg));
    } else if (op.op === "event") {
      if (op.arg && op.arg.type === input.event) {
        seen += 1;
        if (seen === input.nth) {
          advance(1000);
          shoot(0, `${op.arg.type}`);
          playEvent(op.arg);
          for (let k = 1; k <= input.frames; k++) {
            advance(input.interval);
            if (k < input.frames) shoot(k * input.interval, op.arg.type);
          }
          view.destroy();
          host.remove();
          return frames;
        }
      }
      playEvent(op.arg ?? {});
    } else if (op.op === "decisions") view.setDecisions(op.arg ?? []);
    else if (op.op === "overlay") view.setOverlay(op.arg?.id ?? null, op.arg?.data ?? null);
    else if (op.op === "focus") view.focus(op.arg ?? null);
    advance(op.op === "event" ? input.gapMs.event : input.gapMs.other);
  }
  view.destroy();
  host.remove();
  return frames;
}

async function main() {
  const recording = JSON.parse(readFileSync(join(clientRoot, "tests", "fixtures", "floor", "recordings.json"), "utf8"));
  const scenario = recording.scenarios.find((s) => s.id === REC);
  if (!scenario) throw new Error(`没有这个场景：${REC}`);
  const server = await createServer({
    root: join(clientRoot, "src", "renderer"),
    plugins: [react()],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
    logLevel: "error",
    appType: "spa",
  });
  await server.listen();
  const address = server.resolvedUrls?.local[0];
  const browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
  try {
    const page = await browser.newPage({ viewport: { width: 900, height: 400 } });
    await page.goto(`${address}index.html`);
    await page.evaluate((fnSource) => {
      window.__floorLife = (0, eval)(`(${fnSource})`);
    }, driver.toString());
    const frames = await page.evaluate(
      (input) => window.__floorLife(input),
      {
        ops: scenario.ops, gapMs: recording.gapMs, event: EVENT, nth: NTH, frames: FRAMES, interval: INTERVAL,
        toViewSource: toViewState.toString(),
      },
    );
    if (!frames.length) {
      console.log("没有找到事件", EVENT, NTH);
      return;
    }
    // 联系表：每帧一格，两列排开
    const sheet = await page.evaluate(async (fr) => {
      const load = (src) => new Promise((res) => { const im = new Image(); im.onload = () => res(im); im.src = src; });
      const imgs = await Promise.all(fr.map((f) => load(f.url)));
      const cols = 2;
      const w = 640;
      const h = 320;
      const pad = 16;
      const rows = Math.ceil(imgs.length / cols);
      const cv = document.createElement("canvas");
      cv.width = cols * w;
      cv.height = rows * (h + pad);
      const cx = cv.getContext("2d");
      cx.fillStyle = "#111";
      cx.fillRect(0, 0, cv.width, cv.height);
      imgs.forEach((im, i) => {
        const x = (i % cols) * w;
        const y = Math.floor(i / cols) * (h + pad);
        cx.drawImage(im, x, y + pad, w, h);
        cx.fillStyle = "#ffd";
        cx.font = "12px sans-serif";
        cx.fillText(`t=${fr[i].t}ms ${fr[i].note}`, x + 4, y + 12);
      });
      return cv.toDataURL("image/png");
    }, frames);
    const file = join(outDir, OUT);
    writeFileSync(file, Buffer.from(sheet.split(",")[1], "base64"));
    console.log("写入", file, frames.length, "帧");
  } finally {
    await browser.close();
    await server.close();
  }
}

await main();
