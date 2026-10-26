// 部门房间的过程联系表（工单 #177 验收标准 3，#82 的联系表做法）：
// 回放录下的部门房间调用序列，在指定事件之后每隔一段时间截一帧，拼成一张联系表，
// 交给用户查看画风与动作。输出在 client/.tmp/ 下，不进入提交。
//
// 用法：node client/scripts/build-room-contact-sheet.mjs [--rec 场景编号] [--event 事件类型] [--nth 1] [--frames 12] [--interval 300]
// 输出：client/.tmp/room-life/room-<场景>-<事件>-<序号>.png
// 依赖：Playwright 的 Chromium（CHROMIUM_EXE 可以指定位置）。

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";
import { chromium } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..");
const outDir = join(clientRoot, ".tmp", "room-life");
mkdirSync(outDir, { recursive: true });

const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : dflt;
};
const REC = arg("rec", "sc-todo-loop__engineering");
const EVENT = arg("event", "collaboration_requested");
const NTH = Number(arg("nth", 1));
const FRAMES = Number(arg("frames", 12));
const INTERVAL = Number(arg("interval", 300));
const OUT = arg("out", `room-${REC}-${EVENT}-${NTH}.png`);

/** 在页面里运行的驱动：回放录下的调用，在指定事件之后每隔一段时间截一帧。 */
async function driver(input) {
  const P = await import("/src/pixel/room/view.ts");
  const clockMod = await import("/src/pixel/clock.ts");
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:0;top:0;width:480px;height:240px;z-index:9999;background:#000";
  document.body.appendChild(host);
  const clock = clockMod.createManualClock();
  let seed = 987654321;
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const view = await P.createRoomView({ host, clock, department: input.department, random, tween: null });
  const canvas = host.querySelector("canvas");
  const frames = [];
  let seen = 0;
  const shoot = (t, note) => frames.push({ t, note, url: canvas.toDataURL("image/png") });
  const advance = (ms) => {
    const n = Math.max(1, Math.round(ms / 50));
    for (let i = 0; i < n; i++) clock.advance(Math.round(clock.now()) + 50);
  };
  for (let i = 0; i < input.ops.length; i++) {
    const op = input.ops[i];
    if (op.op === "mount" || op.op === "destroy") continue;
    if (op.op === "setModel") view.setModel(op.arg);
    else if (op.op === "playEvent") {
      if (op.arg.type === input.event) {
        seen += 1;
        if (seen === input.nth) {
          advance(1000);
          shoot(0, op.arg.type);
          view.playEvent(op.arg);
          for (let k = 1; k <= input.frames; k++) {
            advance(input.interval);
            if (k < input.frames) shoot(k * input.interval, op.arg.type);
          }
          view.destroy();
          host.remove();
          return frames;
        }
      }
      view.playEvent(op.arg);
    }
    if (op.op === "setModel" || op.op === "playEvent") advance(500);
  }
  view.destroy();
  host.remove();
  return frames;
}

async function main() {
  const recording = JSON.parse(readFileSync(join(clientRoot, "tests", "fixtures", "room", "recordings.json"), "utf8"));
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
    const page = await browser.newPage({ viewport: { width: 1000, height: 300 } });
    await page.goto(`${address}index.html`);
    await page.evaluate((fnSource) => {
      window.__roomLife = (0, eval)(`(${fnSource})`);
    }, driver.toString());
    const frames = await page.evaluate(
      (input) => window.__roomLife(input),
      { ops: scenario.ops, department: scenario.department, event: EVENT, nth: NTH, frames: FRAMES, interval: INTERVAL },
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
      const w = 480;
      const h = 240;
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
