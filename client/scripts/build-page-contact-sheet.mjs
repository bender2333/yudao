// 页面截图联系表（工单 #376 的验收）：把原型 v10 与真实系统的同一个页面在同一种窗口尺寸、
// 设备像素比与主题下并排拼成一张联系表，交给界面工单交付时与原型对照。
// 每一行左侧是原型 v10（自带示例数据，file:// 打开），右侧是真实系统（端到端后端提供的页面文件）。
// 整页截图缩小排布，行尾另附两块按原始像素截取的局部，用来看清晰度。
// 原型一侧的档位由页面清单给出，--level 可以在这一次运行里改用别的档位（例如用 pilot 档看
// 覆盖层的循环、来源与检验三格）。
// 用法：node scripts/build-page-contact-sheet.mjs --issue 376 [--pages home,models] [--themes light,dark] [--level pilot]
// 输出：docs/stage-3/contact-sheets/<工单号>/<页面>-<主题>.png 与 index.md；
//       原始整页截图写在 .tmp/contact-sheet-raw/<工单号>/（被 git 忽略）。
// 依赖：client/out/renderer 的页面构建产物（npm run build:pages）与端到端后端
// （client/tests/e2e/backend.py）。后端的数据目录与浏览器配置都是临时目录，不写用户的数据目录。

import { existsSync, mkdirSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawn } from "node:child_process";
import { chromium } from "@playwright/test";
import { LEVELS, PAGES, THEMES, shotConfigs, sheetFileName } from "./page-contact-sheet-pages.ts";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..");
const repoRoot = resolve(clientRoot, "..");

const args = parseArgs(process.argv.slice(2));
const issue = args.issue ?? fail("命令要带 --issue <工单号>");
if (!/^\d+$/.test(issue)) fail(`--issue 要是工单编号，收到 ${issue}`);
const wanted = args.pages ? args.pages.split(",") : PAGES.map((page) => page.slug);
const pages = wanted.map((slug) => {
  const found = PAGES.find((item) => item.slug === slug);
  if (!found) fail(`页面清单里没有 ${slug}，可选：${PAGES.map((item) => item.slug).join(",")}`);
  return found;
});
const themes = args.themes ? args.themes.split(",") : THEMES;
for (const theme of themes) {
  if (!THEMES.includes(theme)) fail(`主题只有 ${THEMES.join(",")}，收到 ${theme}`);
}

const outDir = join(repoRoot, "docs", "stage-3", "contact-sheets", issue);
const rawDir = join(repoRoot, ".tmp", "contact-sheet-raw", issue);
const backendDataDir = join(repoRoot, ".tmp", "contact-sheet-backend", issue);
const prototypeUrl = pathToFileURL(join(repoRoot, "docs", "prototypes", "v10", "index.html")).href;
const levelArg = args.level ?? null;
if (levelArg !== null && !LEVELS.includes(levelArg)) fail(`档位只有 ${LEVELS.join(",")}，收到 ${levelArg}`);
const deptArg = args.dept ?? args.depts ?? null;
const DEPTS = ["product", "engineering", "quality"];
if (deptArg !== null) {
  for (const d of deptArg.split(",")) {
    if (!DEPTS.includes(d)) fail(`部门只有 ${DEPTS.join(",")}，收到 ${d}`);
  }
}
const pagesToCapture = [];
for (const entry of pages) {
  if (entry.slug === "dept" && deptArg !== null) {
    for (const d of deptArg.split(",")) {
      const dName = { product: "产品", engineering: "工程", quality: "质检" }[d] ?? d;
      pagesToCapture.push({
        ...entry,
        slug: `dept-${d}`,
        name: `部门工作间（${dName}）`,
        prototypeHash: entry.prototypeHash.replace("/dept/engineering", `/dept/${d}`),
        systemHash: entry.systemHash.replace("/dept/engineering", `/dept/${d}`),
      });
    }
  } else {
    pagesToCapture.push(entry);
  }
}
// 联系表的显示尺寸：整页截图按固定显示宽缩小，行尾的局部按原始像素显示（图片不缩放，只露出左上角）
const CELL_WIDTH = 640;
const CROP_WIDTH = 320;
const CROP_HEIGHT = 200;
const PAD = 12;

for (const dir of [outDir, rawDir]) {
  mkdirSync(dir, { recursive: true });
}
// 每次运行用一份干净的后端数据目录：复用上一次的数据会让预置的项目与事项状态带进来
rmSync(backendDataDir, { recursive: true, force: true });
mkdirSync(backendDataDir, { recursive: true });
assertPagesBuildIsCurrent();

const backend = await startBackend();
const browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
const results = [];
try {
  const projects = await readProjects(backend.address);
  const workItems = new Map();
  for (const entry of pagesToCapture) {
    if (entry.systemProject !== null && !workItems.has(entry.systemProject)) {
      workItems.set(entry.systemProject, await readWorkItems(backend.address, projects.get(entry.systemProject)));
    }
  }
  for (const entry of pagesToCapture) {
    for (const theme of themes) {
      const started = Date.now();
      const systemHash = systemHashOf(entry, projects, workItems);
      const prototypeLevel = levelArg ?? entry.prototypeLevel;
      const shots = await captureRow(backend.address, entry, theme, systemHash, prototypeLevel);
      const file = join(outDir, sheetFileName(entry.slug, theme));
      const bytes = await composeSheet(browser, { entry, theme, systemHash, shots, file, prototypeLevel });
      results.push({ entry, theme, systemHash, file, bytes, rows: shots.length, ms: Date.now() - started, prototypeLevel });
      const line = results[results.length - 1];
      console.log(
        `${entry.slug} · ${theme} · ${line.rows} 行 · ${line.ms} 毫秒 · ` +
          `${(bytes / 1024 / 1024).toFixed(2)} MB · ${file}`,
      );
    }
  }
} finally {
  await browser.close();
  await backend.stop();
}

writeFileSync(join(outDir, "index.md"), renderIndex(results));
const totalBytes = results.reduce((sum, item) => sum + item.bytes, 0);
const totalMs = results.reduce((sum, item) => sum + item.ms, 0);
console.log(`索引：${join(outDir, "index.md")}`);
console.log(
  `共 ${results.length} 张联系表、${results.reduce((sum, item) => sum + item.rows, 0)} 行，` +
    `用时 ${(totalMs / 1000).toFixed(1)} 秒，合计 ${(totalBytes / 1024 / 1024).toFixed(2)} MB；原始截图在 ${rawDir}`,
);

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

// 端到端用例的做法（client/tests/e2e/fixtures.ts）：页面构建产物比源码旧时对着旧界面截图，
// 看不出界面已经改过，此时就地报错并写明先构建
function assertPagesBuildIsCurrent() {
  const entry = join(clientRoot, "out", "renderer", "index.html");
  let built;
  try {
    built = statSync(entry).mtimeMs;
  } catch {
    fail(`没有页面构建产物 ${entry}，先运行 npm run build:pages`);
  }
  if (built < newestModification(join(clientRoot, "src", "renderer"))) {
    fail(`页面构建产物 ${entry} 比 client/src/renderer 旧，先运行 npm run build:pages`);
  }
}

function newestModification(directory) {
  let newest = 0;
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    newest = Math.max(newest, entry.isDirectory() ? newestModification(path) : statSync(path).mtimeMs);
  }
  return newest;
}

// 端到端后端：真实接口层、应用层与事件日志，模型回答由 FakeAdapter 给出；数据目录指向临时目录
async function startBackend() {
  const child = spawn(
    "uv",
    ["run", "python", "client/tests/e2e/backend.py", "--port", "0", "--data-dir", backendDataDir],
    { cwd: repoRoot, stdio: ["pipe", "pipe", "pipe"], shell: true },
  );
  const line = await readFirstLine(child);
  const parsed = JSON.parse(line);
  return {
    address: `http://127.0.0.1:${parsed.port}`,
    stop: () =>
      new Promise((done) => {
        const exited = new Promise((finished) => {
          child.on("exit", () => finished());
          setTimeout(() => {
            child.kill();
            finished();
          }, 3000);
        });
        child.stdin.end();
        exited.then(done);
      }),
  };
}

function readFirstLine(child) {
  const { promise, resolve: done, reject } = Promise.withResolvers();
  let buffer = "";
  child.stdout.on("data", (chunk) => {
    buffer += chunk.toString("utf8");
    for (;;) {
      const newline = buffer.indexOf("\n");
      if (newline < 0) {
        break;
      }
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      // uvicorn 的启动提示走标准错误，标准输出只有后端自己打印的那一行端口信息
      if (line.startsWith("{")) {
        done(line);
        return;
      }
    }
  });
  child.stderr.on("data", (chunk) => {
    process.stderr.write(chunk);
  });
  child.on("error", reject);
  child.on("exit", (code) => reject(new Error(`后端提前退出，状态码 ${code}`)));
  return promise;
}

// 预置项目的标识在运行时生成，页面清单里写项目名，这里按名字取出真实标识
async function readProjects(address) {
  const data = await fetchQuery(address, "projects.list");
  const table = new Map();
  for (const row of data.projects) {
    table.set(row.name, row.project_id);
  }
  for (const entry of pages) {
    if (entry.systemProject !== null && !table.has(entry.systemProject)) {
      fail(`端到端后端里没有预置项目「${entry.systemProject}」，页面清单与后端预置对不上`);
    }
  }
  return table;
}

async function readWorkItems(address, projectId) {
  const data = await fetchQuery(address, "project.overview", { project_id: projectId });
  return data.work_items.map((row) => row.work_item_id);
}

async function fetchQuery(address, name, params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    search.set(key, String(value));
  }
  const suffix = search.toString();
  const response = await fetch(`${address}/api/queries/${name}${suffix ? `?${suffix}` : ""}`);
  const envelope = await response.json();
  if (envelope.data === undefined) {
    fail(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  }
  return envelope.data;
}

function systemHashOf(entry, projects, workItems) {
  if (entry.systemProject === null) {
    return entry.systemHash;
  }
  const projectId = projects.get(entry.systemProject);
  const items = workItems.get(entry.systemProject) ?? [];
  if (entry.systemWorkItem && items.length === 0) {
    fail(`预置项目「${entry.systemProject}」没有事项，${entry.name} 的路径里缺事项标识`);
  }
  return entry.systemHash
    .replace("{project}", encodeURIComponent(projectId))
    .replace("{workItem}", encodeURIComponent(items[0] ?? ""));
}

// 逐行截图：每个（窗口、设备像素比）一个浏览器上下文，同一个上下文里先后打开原型与真实系统
async function captureRow(address, entry, theme, systemHash, prototypeLevel) {
  const dir = join(rawDir, `${entry.slug}-${theme}`);
  mkdirSync(dir, { recursive: true });
  const shots = [];
  for (const config of shotConfigs()) {
    const context = await browser.newContext({
      viewport: { width: config.width, height: config.height },
      deviceScaleFactor: config.scaleFactor,
      colorScheme: theme,
    });
    const tag = `${config.width}x${config.height}@${config.scaleFactor}`;
    try {
      const prototypePage = await context.newPage();
      // 原型的档位写在 sessionStorage、主题写在 localStorage（原型 y10.js 的存储键）
      await prototypePage.addInitScript(([level, chosen]) => {
        sessionStorage.setItem("y10.level", JSON.stringify(level));
        localStorage.setItem("y10.theme", JSON.stringify(chosen));
      }, [prototypeLevel, theme]);
      await prototypePage.goto(`${prototypeUrl}${entry.prototypeHash}`);
      await prototypePage.waitForSelector("#y10-content > *");
      await prototypePage.waitForTimeout(1100 + entry.settle);
      // 原型的工具条与提示条只服务于原型演示（切换档位、场景），会盖住页面内容，截图时隐藏
      await prototypePage.addStyleTag({ content: "#y10-toolbar, .y10-banner { display: none !important; }" });
      const prototypeShot = await prototypePage.screenshot({ fullPage: true });
      await prototypePage.close();

      const systemPage = await context.newPage();
      await systemPage.goto(`${address}/${systemHash}`);
      await settleSystem(systemPage, entry);
      if (entry.systemOverlay !== null) {
        await systemPage.locator(".floor-overlay-tabs button", { hasText: entry.systemOverlay }).click();
        await systemPage.waitForTimeout(entry.settle);
      }
      const systemShot = await systemPage.screenshot({ fullPage: true });
      await systemPage.close();

      writeFileSync(join(dir, `${tag}-prototype.png`), prototypeShot);
      writeFileSync(join(dir, `${tag}-system.png`), systemShot);
      shots.push({ config, prototype: prototypeShot, system: systemShot });
    } finally {
      await context.close();
    }
  }
  return shots;
}

// 真实系统的首屏：等外壳连上服务、等读取数据的提示消失，再等像素画面里的走位动画
async function settleSystem(page, entry) {
  await page.waitForSelector(".brand", { timeout: 60_000 });
  const settled = { timeout: 60_000 };
  await page.waitForFunction(() => !document.body.textContent.includes("连接中"), null, settled);
  await page.waitForFunction(() => !document.body.textContent.includes("正在读取"), null, settled);
  await page.waitForTimeout(entry.settle);
}


async function composeSheet(browserRun, { entry, theme, systemHash, shots, file, prototypeLevel }) {
  const rows = shots.map((shot) => rowPlan(shot));
  const totalHeight = rows.reduce((sum, row) => sum + row.height + PAD, 0) + 52;
  const width = PAD * 2 + CELL_WIDTH * 2 + CROP_WIDTH + PAD * 2;
  const sheetPage = await browserRun.newPage({
    viewport: { width: Math.ceil(width), height: Math.ceil(totalHeight) },
  });
  await sheetPage.setContent(sheetHtml(entry, theme, systemHash, rows, prototypeLevel));
  await sheetPage.screenshot({ path: file, fullPage: true });
  await sheetPage.close();
  return statSync(file).size;
}

// 每行的显示尺寸：两格按 CELL_WIDTH 缩小后取较高的一处，行高不低于两块局部占的高度
function rowPlan(shot) {
  const prototype = pngSize(shot.prototype);
  const system = pngSize(shot.system);
  const scaled = Math.max((prototype.height / prototype.width) * CELL_WIDTH, (system.height / system.width) * CELL_WIDTH);
  const cropColumn = 2 * (CROP_HEIGHT + 20) + 20;
  return {
    shot,
    height: Math.ceil(Math.max(Math.round(scaled), cropColumn)),
  };
}

function rowHtml(row, theme, prototypeHash, systemHash) {
  const { shot } = row;
  const label = `窗口 ${shot.config.width}×${shot.config.height} · 设备像素比 ${shot.config.scaleFactor} · 主题 ${theme === "light" ? "浅色" : "深色"}`;
  const cell = (title, href, shot) => `
        <div class="cell">
          <h3>${escapeHtml(title)}</h3>
          <div class="frame" style="height:${row.height - 22}px">
            <img src="data:image/png;base64,${shot.toString("base64")}" alt="">
          </div>
          <p class="hash">${escapeHtml(href)}</p>
        </div>`;
  const crop = (title, shot) => `
          <div class="crop">
            <p class="crop-label">${escapeHtml(title)}</p>
            <div class="window"><img src="data:image/png;base64,${shot.toString("base64")}" alt=""></div>
          </div>`;
  return `
    <section class="row">
      <p class="caption">${escapeHtml(label)}</p>
      <div class="cells">
        ${cell("原型 v10", prototypeHash, shot.prototype)}
        ${cell("真实系统", systemHash, shot.system)}
      </div>
      <div class="crops">
        ${crop("原型 v10 · 原始像素", shot.prototype)}
        ${crop("真实系统 · 原始像素", shot.system)}
      </div>
    </section>`;
}

function sheetHtml(entry, theme, systemHash, rows, prototypeLevel) {
  return `<html lang="zh-CN"><head><meta charset="utf-8"><style>
      * { box-sizing: border-box; }
      body { margin: 0; background: #eef0ef; color: #1c201d;
             font: 13px/1.4 "Microsoft YaHei", "PingFang SC", sans-serif; }
      .head { padding: 10px ${PAD}px 8px; font-size: 13px; }
      .head b { font-size: 18px; }
      .head span { color: #55605a; }
      .row { padding: ${PAD}px; }
      .caption { margin: 0 0 6px; font-size: 14px; font-weight: 600; }
      .cells { display: flex; gap: ${PAD}px; }
      .cell { width: ${CELL_WIDTH}px; }
      .cell h3 { margin: 0 0 4px; font-size: 13px; }
      .frame { border: 1px solid #b9c2bc; background: #fff; overflow: hidden; }
      .frame img { display: block; width: 100%; }
      .hash { margin: 4px 0 0; color: #6b766f; font-size: 11px; word-break: break-all; }
      .crops { margin-top: ${PAD}px; display: flex; gap: ${PAD}px; }
      .crop { width: ${CROP_WIDTH}px; }
      .crop-label { margin: 0 0 3px; font-size: 12px; }
      .window { width: ${CROP_WIDTH}px; height: ${CROP_HEIGHT}px; overflow: hidden;
                border: 1px solid #b9c2bc; background: #fff; }
      .window img { display: block; max-width: none; }
    </style></head><body>
    <div class="head"><b>${escapeHtml(entry.name)} · ${theme === "light" ? "浅色" : "深色"}</b>
      <span>左：原型 v10（${escapeHtml(entry.prototypeHash)}，档位 ${escapeHtml(prototypeLevel)}）　
      右：真实系统（${escapeHtml(systemHash)}）　行尾：两侧按原始像素显示的局部</span></div>
    ${rows.map((row) => rowHtml(row, theme, entry.prototypeHash, systemHash)).join("")}
  </body></html>`;
}

function escapeHtml(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// PNG 头部的 IHDR 段里是宽高
function pngSize(buffer) {
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

// 索引列出输出目录里现存的全部联系表：分批运行同一命令时，前面几批生成的图片照样出现在索引里
function renderIndex(results) {
  const fresh = new Map(results.map((item) => [sheetFileName(item.entry.slug, item.theme), item]));
  const lines = [
    `# 截图联系表 · 工单 #${issue}`,
    "",
    "原型 v10 与真实系统的同一个页面并排。每张联系表六行：1440×900 与 1920×1080 两种窗口乘设备像素比 1、1.25、1.5；",
    "每行左侧是原型 v10，右侧是真实系统，行尾附两侧按原始像素显示的局部。",
    "",
    "真实系统一侧用端到端后端（`client/tests/e2e/backend.py` 的 default 预置：真实接口层、应用层与事件日志，",
    "模型回答由 FakeAdapter 给出）；页面清单里的预置项目名在运行时换成服务端生成的项目标识。",
    "机器、运行、工具与恢复四个页面在真实系统里当前是占位内容（由工单 #378、#380 填入），联系表照拍占位画面。",
    "",
  ];
  const allEntries = [...PAGES];
  for (const item of results) {
    if (!allEntries.some((entry) => entry.slug === item.entry.slug)) {
      allEntries.push(item.entry);
    }
  }
  for (const theme of THEMES) {
    lines.push(`## ${theme === "light" ? "浅色" : "深色"}`, "");
    for (const entry of allEntries) {
      const name = sheetFileName(entry.slug, theme);
      const file = join(outDir, name);
      if (!existsSync(file)) {
        continue;
      }
      const item = fresh.get(name);
      const rows = item ? item.rows : countRawRows(join(rawDir, `${entry.slug}-${theme}`));
      const systemHash = item ? item.systemHash : entry.systemHash;
      const project = entry.systemProject === null ? "（系统页，不选项目）" : ` · 预置项目「${entry.systemProject}」`;
      const overlay = entry.systemOverlay === null ? "" : ` · 覆盖层「${entry.systemOverlay}」`;
      const prototypeLevel = item ? item.prototypeLevel : entry.prototypeLevel;
      lines.push(
        `### ${entry.name}（${entry.slug}）`,
        "",
        `![${entry.name} · ${theme}](${name})`,
        "",
        `- 原型 v10 路由：\`${entry.prototypeHash}\`（档位 \`${prototypeLevel}\`，用原型自带的示例数据）`,
        `- 真实系统路由：\`${systemHash}\`${project}${overlay}`,
        `- 行数：${rows} · 图片体积：${(statSync(file).size / 1024 / 1024).toFixed(2)} MB`,
        "",
      );
    }
  }
  lines.push(
    "## 重新生成",
    "",
    "```",
    "cd client && npm run build:pages",
    `node scripts/build-page-contact-sheet.mjs --issue ${issue}`,
    `node scripts/build-page-contact-sheet.mjs --issue ${issue} --pages home,models --themes light,dark`,
    `node scripts/build-page-contact-sheet.mjs --issue ${issue} --pages overview --themes light --level pilot`,
    "```",
    "",
    "页面清单与截图矩阵：`client/scripts/page-contact-sheet-pages.ts`（单元测试 `client/tests/unit/page-contact-sheet.test.ts`）。",
    `原始整页截图写在 \`.tmp/contact-sheet-raw/${issue}/\`，被 git 忽略。`,
    "",
  );
  return lines.join("\n");
}

// 原始截图目录里的行数：每一行一对（原型与真实系统）
function countRawRows(dir) {
  if (!existsSync(dir)) {
    return 0;
  }
  return readdirSync(dir).filter((name) => name.endsWith("-prototype.png")).length;
}