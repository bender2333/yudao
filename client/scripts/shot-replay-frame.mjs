// 回放中的一帧整页截图（工单 #379 的验收材料）：原型 v9 没有回放位置参数，
// 回放一帧不与原型并排，单独按真实系统拍整页截图，两张（浅色、深色）写进工单的联系表目录。
//
// 用法：node scripts/shot-replay-frame.mjs --issue 379
// 输出：docs/stage-3/contact-sheets/<工单号>/overview-replay-<主题>.png
// 依赖：client/out/renderer 的页面构建产物（npm run build:pages）与端到端后端
//（client/tests/e2e/backend.py）；后端数据目录是临时目录，不写用户的数据目录。

import { existsSync, rmSync, statSync, writeFileSync } from "node:fs";
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { chromium } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..");
const repoRoot = resolve(clientRoot, "..");

const args = parseArgs(process.argv.slice(2));
const issue = args.issue ?? fail("命令要带 --issue <工单号>");
if (!/^\d+$/.test(issue)) fail(`--issue 要是工单编号，收到 ${issue}`);

const entry = join(clientRoot, "out", "renderer", "index.html");
if (!existsSync(entry)) fail(`没有页面构建产物 ${entry}，先运行 npm run build:pages`);

const outDir = join(repoRoot, "docs", "stage-3", "contact-sheets", issue);
mkdirSync(outDir, { recursive: true });
const dataDir = join(repoRoot, ".tmp", "contact-sheet-replay", issue);
rmSync(dataDir, { recursive: true, force: true });
mkdirSync(dataDir, { recursive: true });

const backend = await startBackend();
const browser = await chromium.launch();
try {
  const projects = await fetchQuery(backend.address, "projects.list");
  const project = projects.projects.find((row) => row.name === "交付历史");
  if (project === undefined) fail("端到端后端里没有预置项目「交付历史」");

  for (const theme of ["light", "dark"]) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: theme });
    try {
      const page = await context.newPage();
      await page.goto(`${backend.address}/#/p/${project.project_id}/overview`);
      await settleOverview(page);
      // 拖到时间轴上最早的那一格：位置取自界面上的刻度，回放状态由路径上的 at 给出
      const positions = await page.locator(".timeline .tick[data-position]")
        .evaluateAll((nodes) => nodes.map((node) => node.dataset.position));
      if (positions.length === 0) fail("概览页的时间轴上没有刻度，回放一帧拍不出来");
      await page.locator(`.timeline .tick[data-position="${positions[0]}"]`).click();
      await page.waitForSelector(".replay-banner", { timeout: 60_000 });
      await page.waitForTimeout(2000);
      const file = join(outDir, `overview-replay-${theme}.png`);
      writeFileSync(file, await page.screenshot({ fullPage: true }));
      console.log(`${theme} · ${(statSync(file).size / 1024).toFixed(0)} KB · ${file}`);
    } finally {
      await context.close();
    }
  }
} finally {
  await browser.close();
  await backend.stop();
}

function parseArgs(list) {
  const result = {};
  for (let i = 0; i < list.length; i++) {
    const item = list[i];
    if (!item.startsWith("--")) fail(`参数写法是 --名字=值 或 --名字 值，收到 ${item}`);
    const name = item.slice(2);
    if (name.includes("=")) {
      const [key, value = ""] = name.split("=");
      result[key] = value;
      continue;
    }
    const next = list[i + 1];
    if (next === undefined || next.startsWith("--")) fail(`参数 ${item} 缺值`);
    result[name] = next;
    i++;
  }
  return result;
}
function fail(message) {
  console.error(message);
  process.exit(1);
}

// 端到端后端：真实接口层、应用层与事件日志，模型回答由 FakeAdapter 给出
async function startBackend() {
  const child = spawn("uv", ["run", "python", "client/tests/e2e/backend.py", "--port", "0", "--data-dir", dataDir],
    { cwd: repoRoot, stdio: ["pipe", "pipe", "pipe"], shell: true });
  const address = new Promise((done, reject) => {
    let buffer = "";
    child.stdout.on("data", (chunk) => {
      buffer += chunk.toString("utf8");
      const newline = buffer.indexOf("\n");
      if (newline >= 0) done(`http://127.0.0.1:${JSON.parse(buffer.slice(0, newline)).port}`);
    });
    child.stderr.on("data", (chunk) => process.stderr.write(chunk));
    child.on("exit", (code) => reject(new Error(`后端提前退出，状态码 ${code}`)));
  });
  return {
    address: await address,
    stop: () =>
      new Promise((done) => {
        child.on("exit", () => done());
        child.stdin.end();
        setTimeout(() => {
          child.kill();
          done();
        }, 3000);
      }),
  };
}

async function settleOverview(page) {
  const settled = { timeout: 60_000 };
  await page.waitForSelector(".brand", settled);
  await page.waitForFunction(() => !document.body.textContent.includes("连接中"), null, settled);
  await page.waitForFunction(() => !document.body.textContent.includes("正在读取"), null, settled);
  await page.waitForSelector(".timeline .tick[data-position]", settled);
  await page.waitForTimeout(1600);
}

async function fetchQuery(address, name, params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) search.set(key, String(value));
  const suffix = search.toString();
  const envelope = await fetch(`${address}/api/queries/${name}${suffix ? `?${suffix}` : ""}`).then((r) => r.json());
  if (envelope.data === undefined) fail(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  return envelope.data;
}
