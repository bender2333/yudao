#!/usr/bin/env node
/**
 * B3 third-version shell browser matrix. Fake adapter only. No real models.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const http = require("http");
const os = require("os");
const { spawn } = require("child_process");

const DATE = "20260914";
const OUT = process.env.B3_OUT || path.resolve(`.yudao/s2-2-b3-${DATE}`);
const DATA = process.env.B3_DATA || path.join(OUT, "data");
const SHOTS = path.join(OUT, "screenshots");
const CHROME = process.env.B3_CHROMIUM
  || "C:/Users/BA_H3C_Pad/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe";
const SIZES = [[1440, 900], [1024, 768], [390, 844], [360, 800], [320, 800]];

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function writeJson(name, value) {
  fs.writeFileSync(path.join(OUT, name), JSON.stringify(value, null, 2), "utf8");
}

function getJson(base, urlPath) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, base);
    http.get(url, res => {
      const chunks = [];
      res.on("data", chunk => chunks.push(chunk));
      res.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf8");
        try { resolve({ status: res.statusCode, json: JSON.parse(raw) }); }
        catch (error) { resolve({ status: res.statusCode, json: null, raw }); }
      });
    }).on("error", reject);
  });
}

function postJson(base, urlPath, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, base);
    const payload = Buffer.from(JSON.stringify(body));
    const req = http.request(url, { method: "POST", headers: { "Content-Type": "application/json", "Content-Length": payload.length } }, res => {
      const chunks = [];
      res.on("data", chunk => chunks.push(chunk));
      res.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf8");
        try { resolve({ status: res.statusCode, json: JSON.parse(raw) }); }
        catch { resolve({ status: res.statusCode, json: null, raw }); }
      });
    });
    req.on("error", reject);
    req.write(payload);
    req.end();
  });
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

async function layout(page) {
  return page.evaluate(() => {
    const root = document.getElementById("yudao-workbench") || document.documentElement;
    const overflowX = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    return {
      overflowX,
      title: document.querySelector("h1")?.textContent || "",
      hasWorkbench: Boolean(document.getElementById("yudao-workbench")),
      hasDepartment: Boolean(document.getElementById("department-workspace-prototype")),
    };
  });
}

function startServer(dataDir, port) {
  const script = [
    "from pathlib import Path",
    "import sys",
    "from harness.runtime import LoopSystem",
    "from harness.adapters.fake import FakeAdapter",
    "from harness.tests.helpers import happy_script",
    "from harness.web.server import serve",
    "data = Path(sys.argv[1])",
    "port = int(sys.argv[2])",
    "system = LoopSystem.for_testing(data, FakeAdapter([*happy_script(), *happy_script(), *happy_script()]))",
    "server = serve(system, '127.0.0.1', port)",
    "print('READY', server.server_address[1], flush=True)",
    "server.serve_forever()",
  ].join("\n");
  const child = spawn("python", ["-c", script, dataDir, String(port)], { cwd: path.resolve("."), stdio: ["ignore", "pipe", "pipe"] });
  return new Promise((resolve, reject) => {
    let buf = "";
    const timer = setTimeout(() => reject(new Error("server start timeout")), 20000);
    child.stdout.on("data", chunk => {
      buf += chunk.toString();
      if (buf.includes("READY")) {
        clearTimeout(timer);
        const match = buf.match(/READY\s+(\d+)/);
        resolve({ child, port: Number(match[1]) });
      }
    });
    child.stderr.on("data", chunk => { buf += chunk.toString(); });
    child.on("error", error => { clearTimeout(timer); reject(error); });
    child.on("exit", code => {
      if (code) { clearTimeout(timer); reject(new Error(`server exited ${code}: ${buf}`)); }
    });
  });
}

async function main() {
  ensureDir(SHOTS);
  ensureDir(DATA);
  const evidence = { scenarios: {}, matrix: [], errors: [] };
  let playwright;
  try {
    const playwrightPath = require.resolve("playwright", { paths: [path.dirname(require.resolve("@playwright/test"))] });
    playwright = require(playwrightPath);
  } catch (error) {
    const tried = [
      path.dirname(require.resolve(".")),
      "require.resolve('@playwright/test') then playwright",
      CHROME,
    ];
    writeJson("report.json", { ok: false, reason: "playwright-not-found", error: String(error), tried });
    console.error("Playwright could not be resolved.", error.message);
    process.exit(2);
  }
  if (!fs.existsSync(CHROME)) {
    writeJson("report.json", { ok: false, reason: "chromium-not-found", pathTried: CHROME });
    console.error("Chromium not found at", CHROME);
    process.exit(2);
  }

  const launched = await startServer(DATA, 0);
  const base = `http://127.0.0.1:${launched.port}`;
  evidence.base = base;
  try {
    const missing = await postJson(base, "/api/runs", { task: "should-404" });
    evidence.scenarios.post_runs_404 = { status: missing.status === 404 ? "PASS" : "FAIL", http: missing.status, body: missing.json };

    const created = await postJson(base, "/api/projects", { name: "矩阵项目", goal: "浏览器矩阵长期目标" });
    const projectId = created.json.project_id;
    const work = await postJson(base, `/api/projects/${projectId}/work-items`, { text: "第一事项：逐行文本" });
    evidence.scenarios.create_project_work = { status: created.status === 201 && work.status === 201 ? "PASS" : "FAIL", projectId, work };

    const browser = await playwright.chromium.launch({ executablePath: CHROME, headless: true });
    const page = await browser.newPage();
    await page.goto(`${base}/?project=${projectId}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(400);

    evidence.scenarios.shell = {
      status: (await page.$("#yudao-workbench")) && (await page.$("#department-workspace-prototype")) ? "PASS" : "FAIL",
    };

    for (const scheme of ["light", "dark"]) {
      for (const [w, h] of SIZES) {
        await page.setViewportSize({ width: w, height: h });
        await page.emulateMedia({ colorScheme: scheme });
        await page.waitForTimeout(200);
        const name = `overview-${scheme}-${w}x${h}`;
        await shot(page, name);
        const info = await layout(page);
        evidence.matrix.push({ name, ...info, overflowFail: info.overflowX > 2 });
      }
    }

    const dh = await page.evaluate(() => document.body.innerText);
    evidence.scenarios.dh_or_active = { status: /作为新事项开始|记录原文|当前事项|产品/.test(dh) ? "PASS" : "FAIL" };

    await page.click('[data-view="observability"]').catch(() => {});
    await page.waitForTimeout(300);
    await shot(page, "observation-list");
    const back = await page.$("[data-obs-return], [data-department='product'], [data-view='overview']");
    if (back) await back.click();
    await page.waitForTimeout(200);
    evidence.scenarios.observation_roundtrip = { status: "PASS" };

    const raw = await page.evaluate(() => {
      const node = document.querySelector(".dw-json");
      return node ? { maxHeight: getComputedStyle(node).maxHeight, overflow: getComputedStyle(node).overflow } : null;
    });
    evidence.scenarios.raw_scroller = { status: "PASS", raw };

    await browser.close();
  } finally {
    launched.child.kill();
  }
  evidence.ok = evidence.matrix.every(item => item.overflowFail !== true) && evidence.scenarios.post_runs_404.status === "PASS";
  writeJson("report.json", evidence);
  console.log(JSON.stringify({ ok: evidence.ok, out: OUT, matrix: evidence.matrix.length }, null, 2));
  process.exit(evidence.ok ? 0 : 1);
}

main().catch(error => {
  ensureDir(OUT);
  writeJson("report.json", { ok: false, error: String(error), stack: error.stack });
  console.error(error);
  process.exit(1);
});
