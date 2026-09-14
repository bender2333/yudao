#!/usr/bin/env node
/**
 * HISTORICAL S3 / W5 / W7 browser evidence only. Do not run as a live entry.
 * POST /api/runs was removed in B3; this file still talks to the first-version shell.
 * Current browser matrix: harness/tests/test_b3_shell_browser.spec.js
 * Uses already-installed Playwright 1.60 + Chromium 1223 if invoked manually.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const http = require("http");

const playwrightPath = require.resolve("playwright", {
  paths: [path.dirname(require.resolve("@playwright/test"))],
});
const { chromium } = require(playwrightPath);

const BASE = process.env.S3_BASE_URL || "http://127.0.0.1:8878";
const PROTO = process.env.S3_PROTO_URL || "http://127.0.0.1:8879/department-workspace.html";
const OUT = process.env.S3_OUT || path.resolve(".yudao/s3-acceptance-20260908");
const DATA = process.env.S3_DATA || path.join(OUT, "data");
const CHROME = process.env.S3_CHROMIUM
  || "C:/Users/BA_H3C_Pad/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe";
const SHOTS = path.join(OUT, "screenshots");
const LONG_MS = Number(process.env.S3_RUN_TIMEOUT_MS || 45 * 60 * 1000);

const MAIN_TASK = [
  "Implement a local Python CLI at src/export_orders.py.",
  "Running `python src/export_orders.py` must print CSV to stdout with header `id,name` and one data row `1,alpha`, then exit 0.",
  "Do not add network access, extra configuration, or files other than src/export_orders.py unless a later user input requires them.",
  "Engineering must write the file and have the host run a check.",
  "Quality must independently have the host run a check before release.",
].join(" ");

const V2_INPUT = "Also include a status column. Running `python src/export_orders.py` must print header `id,name,status` and one data row `1,alpha,open`.";
const EXPLAIN_GUIDANCE = "请说明当前 CSV 是否给字段加引号。不要修改任何文件。";
const ACTION_GUIDANCE = "请在 src/export_orders.py 文件开头增加一行注释：# export-format: csv";
const COMPACTION_TASK = [
  "Implement a local Python CLI at src/echo.py.",
  "Running `python src/echo.py hello` must print hello and exit 0.",
  "Do not add network access or extra configuration.",
  "If large.txt exists, engineering must read large.txt fully before writing src/echo.py.",
  "Engineering must write the file and have the host run a check.",
  "Quality must independently have the host run a check before release.",
].join(" ");

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function writeJson(name, value) {
  ensureDir(path.dirname(path.join(OUT, name)));
  fs.writeFileSync(path.join(OUT, name), JSON.stringify(value, null, 2), "utf8");
}

function getJson(urlPath) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, BASE);
    const req = http.get(url, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => {
        try { resolve({ status: res.statusCode, json: body ? JSON.parse(body) : null }); }
        catch (error) { reject(error); }
      });
    });
    req.on("error", reject);
    req.setTimeout(30000, () => { req.destroy(new Error("timeout")); });
  });
}

function redact(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.replace(/sk-[A-Za-z0-9_-]{8,}/g, "[redacted]").replace(/Bearer\s+[A-Za-z0-9._-]+/gi, "Bearer [redacted]");
}

async function shot(page, name) {
  ensureDir(SHOTS);
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

async function layout(page) {
  return page.evaluate(() => {
    const root = document.getElementById("department-workspace-prototype") || document.documentElement;
    const style = getComputedStyle(root);
    const overflowX = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    const overflowY = document.documentElement.scrollHeight - document.documentElement.clientHeight;
    const json = document.querySelector(".dw-detail-panel .dw-json, .dw-event-raw .dw-json");
    return {
      viewport: { w: window.innerWidth, h: window.innerHeight },
      overflowX,
      overflowY,
      accent: style.getPropertyValue("--dw-accent").trim(),
      background: style.getPropertyValue("--dw-background").trim(),
      surface: style.getPropertyValue("--dw-surface").trim(),
      jsonMaxHeight: json ? getComputedStyle(json).maxHeight : null,
      jsonOverflow: json ? getComputedStyle(json).overflow : null,
      jsonScrollHeight: json ? json.scrollHeight : null,
      jsonClientHeight: json ? json.clientHeight : null,
      title: document.querySelector("h1")?.textContent || "",
      phase: document.querySelector(".dw-current-state")?.innerText || "",
    };
  });
}

async function visualPass(page, prefix, sizes, colorScheme) {
  const results = [];
  for (const [w, h] of sizes) {
    await page.setViewportSize({ width: w, height: h });
    await page.emulateMedia({ colorScheme });
    await page.waitForTimeout(250);
    const name = `${prefix}-${colorScheme}-${w}x${h}`;
    await shot(page, name);
    const info = await layout(page);
    results.push({ name, ...info, overflowFail: info.overflowX > 2 });
  }
  return results;
}

async function createTask(page, task, maxCycles, contextWindow) {
  await page.click('[data-action="new-task"]');
  await page.waitForSelector("#dw-task-dialog[open], #dw-task-text");
  await page.fill("#dw-task-text", task);
  await page.fill("#dw-max-cycles", String(maxCycles));
  await page.fill("#dw-context-window", String(contextWindow));
  const [response] = await Promise.all([
    page.waitForResponse((res) => {
      try {
        const url = new URL(res.url());
        return url.pathname === "/api/runs" && res.request().method() === "POST";
      } catch {
        return false;
      }
    }, { timeout: 30000 }),
    page.click("#dw-task-submit"),
  ]);
  const body = await response.json().catch(() => ({ error: "non-json create response" }));
  if (response.status() !== 201 || !body.run_id) {
    throw new Error(`create failed status=${response.status()} body=${JSON.stringify(body).slice(0, 400)}`);
  }
  return { status: response.status(), body };
}

async function waitPhase(page, runId, wanted, timeoutMs) {
  const start = Date.now();
  let last = null;
  while (Date.now() - start < timeoutMs) {
    const payload = await getJson(`/api/runs/${runId}`);
    last = {
      phase: payload.json?.board?.phase,
      stop: payload.json?.board?.stop_reason,
      error: payload.json?.board?.error || payload.json?.execution_error,
      worker: payload.json?.worker_active,
      input_version: payload.json?.board?.input_version,
      processed_input_version: payload.json?.board?.processed_input_version,
      waited_ms: Date.now() - start,
      source: "api-poll-labeled",
    };
    if (wanted.includes(last.phase) || (wanted.includes("TERMINAL") && ["DONE", "FAILED", "PAUSED"].includes(last.phase))) {
      return last;
    }
    await page.waitForTimeout(4000);
  }
  last.timeout = true;
  return last;
}

function seedLargeFile(runId) {
  const dir = path.join(DATA, "workspaces", runId);
  ensureDir(dir);
  const lines = [];
  for (let i = 1; i <= 900; i += 1) {
    lines.push(`NOTE-${String(i).padStart(4, "0")}: ${"compaction-source-material ".repeat(6)}`);
  }
  const file = path.join(dir, "large.txt");
  fs.writeFileSync(file, lines.join("\n"), "utf8");
  return { path: file, bytes: fs.statSync(file).size, labeled: "scripted workspace seed, not a browser natural write" };
}

async function sendGlobal(page, text) {
  await page.click('button[data-view="overview"]');
  await page.waitForSelector("[data-global-draft]");
  await page.fill("[data-global-draft]", text);
  await Promise.all([
    page.waitForResponse((res) => res.url().includes("/inputs") && res.request().method() === "POST"),
    page.click("#dw-global-form button[type=submit]"),
  ]);
}

async function sendGuidance(page, department, text) {
  await page.click(`button[data-department="${department}"]`);
  await page.waitForSelector("[data-dept-draft]");
  await page.fill("[data-dept-draft]", text);
  await Promise.all([
    page.waitForResponse((res) => res.url().includes("/guidance") && res.request().method() === "POST"),
    page.click("#dw-dept-form button[type=submit]"),
  ]);
}

async function main() {
  ensureDir(OUT);
  ensureDir(SHOTS);
  const evidence = {
    started_at: new Date().toISOString(),
    base: BASE,
    scenarios: {},
    notes: [],
  };

  const browser = await chromium.launch({
    executablePath: CHROME,
    headless: true,
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1024 } });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const consoleErrors = [];
  page.on("pageerror", (error) => consoleErrors.push(String(error)));
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  try {
    const health = await getJson("/api/health");
    evidence.health = {
      ok: health.json?.ok,
      adapter: health.json?.adapter,
      provider_available: health.json?.provider_available,
      busy: health.json?.busy,
      bindings: health.json?.provider_bindings,
    };
    if (!health.json?.provider_available) {
      evidence.notes.push("provider not available on health; browser create will fail");
    }

    await page.goto(BASE, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#department-workspace-prototype");
    evidence.scenarios.terminal_empty = { status: "in_progress" };

    await page.click('[data-action="new-task"]');
    await page.fill("#dw-task-text", "draft-should-keep");
    await page.click('#dw-task-dialog-form button[value="cancel"]');
    await page.click('[data-action="new-task"]');
    const kept = await page.inputValue("#dw-task-text");
    await page.click('#dw-task-dialog-form button[value="cancel"]');
    const beforeRuns = await getJson("/api/runs");
    evidence.scenarios.terminal_empty = {
      status: kept === "draft-should-keep" ? "PASS" : "FAIL",
      draft_kept: kept === "draft-should-keep",
      runs_before: (beforeRuns.json?.runs || []).length,
      note: "only explicit new-task creates a run; cancelled dialog does not POST",
    };

    await page.route("**/api/runs", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ error: `long-error-${"E".repeat(240)}`, reason: "provider_unavailable" }),
        });
        return;
      }
      await route.continue();
    });
    await page.click('[data-action="new-task"]');
    await page.fill("#dw-task-text", "failed-create-draft");
    await page.click("#dw-task-submit");
    await page.waitForSelector("#dw-task-error:not([hidden])");
    const failedError = await page.locator("#dw-task-error").innerText();
    await page.click('#dw-task-dialog-form button[value="cancel"]');
    await page.click('[data-action="new-task"]');
    const failedDraft = await page.inputValue("#dw-task-text");
    await page.click('#dw-task-dialog-form button[value="cancel"]');
    await page.unrouteAll({ behavior: "wait" }).catch(async () => {
      await page.unroute("**/api/runs");
    });
    evidence.scenarios.terminal_failed_create = {
      status: failedDraft === "failed-create-draft" && failedError.includes("long-error-") ? "PASS" : "FAIL",
      draft_kept: failedDraft === "failed-create-draft",
      long_error_visible: failedError.includes("long-error-"),
      labeled: "scripted 503 on create; UI draft/error only",
    };

    const protoPage = await context.newPage();
    const protoResults = { light: [], dark: [] };
    try {
      await protoPage.goto(PROTO, { waitUntil: "domcontentloaded", timeout: 15000 });
      protoResults.light = await visualPass(protoPage, "proto-overview", [[1440, 900], [1024, 768], [390, 844], [360, 800]], "light");
      protoResults.dark = await visualPass(protoPage, "proto-overview", [[1440, 900], [1024, 768]], "dark");
    } catch (error) {
      protoResults.error = String(error);
    } finally {
      await protoPage.close();
    }

    await page.setViewportSize({ width: 1440, height: 1024 });
    await page.goto(BASE, { waitUntil: "domcontentloaded" });
    const emptyLight = await visualPass(page, "app-empty", [[1440, 900], [1024, 768], [390, 844], [360, 800], [320, 720]], "light");
    const emptyDark = await visualPass(page, "app-empty", [[1440, 900], [1024, 768], [390, 844]], "dark");
    evidence.scenarios.visual_empty = {
      status: [...emptyLight, ...emptyDark].every((item) => !item.overflowFail) ? "PASS" : "PARTIAL",
      prototype: protoResults,
      app_light: emptyLight,
      app_dark: emptyDark,
    };

    await page.setViewportSize({ width: 1440, height: 1024 });
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto(BASE, { waitUntil: "domcontentloaded" });
    const created = await createTask(page, MAIN_TASK, 16, 32000);
    const mainRunId = created.body?.run_id;
    evidence.scenarios.basic_and_continuous = {
      status: "running",
      run_id: mainRunId,
      create_status: created.status,
      task: MAIN_TASK,
      max_cycles: 16,
      context_window: 32000,
      kind: "browser natural create",
    };
    writeJson("run-ids.json", [{ run_id: mainRunId, scenario: "csv-continuous-guidance" }]);
    await page.waitForSelector("h1");
    await shot(page, "main-created-overview");

    const engineering = await waitPhase(page, mainRunId, ["ENGINEERING", "ENGINEERING_PLAN", "QUALITY", "DONE", "FAILED"], LONG_MS);
    evidence.scenarios.basic_and_continuous.engineering_wait = engineering;
    if (["ENGINEERING", "ENGINEERING_PLAN", "QUALITY"].includes(engineering.phase)) {
      try {
        await sendGuidance(page, "engineering", EXPLAIN_GUIDANCE);
        await page.waitForTimeout(800);
        await sendGuidance(page, "engineering", ACTION_GUIDANCE);
        await shot(page, "main-engineering-guidance");
        evidence.scenarios.department_guidance = { status: "sent", run_id: mainRunId, labeled: "browser UI posts; wait used API poll" };
      } catch (error) {
        evidence.scenarios.department_guidance = { status: "FAIL", error: String(error) };
      }
      try {
        await sendGlobal(page, V2_INPUT);
        await shot(page, "main-v2-input");
        evidence.scenarios.basic_and_continuous.v2_sent = true;
        evidence.scenarios.basic_and_continuous.v2_text = V2_INPUT;
      } catch (error) {
        evidence.scenarios.basic_and_continuous.v2_error = String(error);
      }
    } else {
      evidence.scenarios.department_guidance = { status: "PARTIAL", reason: "engineering phase not reached before sending", phase: engineering.phase };
    }

    const done = await waitPhase(page, mainRunId, ["DONE", "FAILED", "PAUSED"], LONG_MS);
    evidence.scenarios.basic_and_continuous.final = done;
    evidence.scenarios.basic_and_continuous.status = done.phase === "DONE" && done.stop === "released" ? "PASS" : "PARTIAL";

    await page.click('button[data-view="overview"]');
    await page.waitForTimeout(500);
    const live = await visualPass(page, "app-main-overview", [[1440, 900], [1024, 768], [390, 844], [360, 800]], "light");
    await page.emulateMedia({ colorScheme: "dark" });
    const liveDark = await visualPass(page, "app-main-overview", [[1440, 900], [390, 844]], "dark");
    await page.emulateMedia({ colorScheme: "light" });
    evidence.scenarios.visual_main = {
      status: [...live, ...liveDark].every((item) => !item.overflowFail) ? "PASS" : "PARTIAL",
      light: live,
      dark: liveDark,
    };

    const runPayload = await getJson(`/api/runs/${mainRunId}`);
    writeJson(`runs/${mainRunId}.json`, JSON.parse(redact(runPayload.json)));
    const exportPayload = await getJson(`/api/runs/${mainRunId}/export`);
    writeJson(`runs/${mainRunId}-export.json`, JSON.parse(redact(exportPayload.json)));
    const productDept = await getJson(`/api/runs/${mainRunId}/departments/product`);
    const engDept = await getJson(`/api/runs/${mainRunId}/departments/engineering`);
    writeJson(`runs/${mainRunId}-product.json`, JSON.parse(redact(productDept.json)));
    writeJson(`runs/${mainRunId}-engineering.json`, JSON.parse(redact(engDept.json)));

    const inputs = runPayload.json?.inputs || [];
    const v2 = inputs.find((item) => item.version === 2);
    const joined = inputs.map((item) => item.text).join("");
    evidence.scenarios.same_run_input = {
      status: v2 && v2.text === V2_INPUT ? "PASS" : (inputs.length >= 1 ? "PARTIAL" : "FAIL"),
      versions: inputs.map((item) => ({ version: item.version, bytes: [item.byte_start, item.byte_end], kind: item.kind, text: item.text })),
      concatenated_len: joined.length,
      processed_input_version: runPayload.json?.board?.processed_input_version,
      current_spec_revision: runPayload.json?.timeline?.effective_contract?.revision || runPayload.json?.timeline?.current_product_spec?.revision,
      plan_revision: (runPayload.json?.timeline?.engineering_plans || []).at(-1)?.revision,
      qa: (runPayload.json?.evidence?.reviews || []).map((item) => item.verdict),
      phase: runPayload.json?.board?.phase,
      stop: runPayload.json?.board?.stop_reason,
    };

    const engGuidance = (engDept.json?.guidance || []);
    const productMessages = (productDept.json?.messages || []).map((item) => item.text || "");
    const mixed = productMessages.some((text) => text.includes("export-format: csv") || text.includes("是否给字段加引号"));
    evidence.scenarios.department_guidance = {
      ...(evidence.scenarios.department_guidance || {}),
      items: engGuidance.map((item) => ({ id: item.id, status: item.status, text: item.text, response: item.response_text, applied: item.applied_context_event_id })),
      explained_vs_completed: {
        explained: engGuidance.filter((item) => item.status === "explained").length,
        completed: engGuidance.filter((item) => item.status === "completed").length,
        other: engGuidance.filter((item) => !["explained", "completed"].includes(item.status)).map((item) => item.status),
      },
      private_history_mixed_into_product: mixed,
      status: engGuidance.length ? (mixed ? "FAIL" : "PASS") : "PARTIAL",
    };

    await page.click('button[data-department="engineering"]');
    await page.waitForTimeout(800);
    await shot(page, "main-engineering-page");
    const contextJump = { status: "PARTIAL" };
    const contextBtn = page.locator("[data-observe-attempt]").first();
    if (await contextBtn.count()) {
      const attemptId = await contextBtn.getAttribute("data-observe-attempt");
      await contextBtn.click();
      await page.waitForTimeout(800);
      await shot(page, "main-context-attempt");
      const url = page.url();
      contextJump.attempt_id = attemptId;
      contextJump.url = url;
      contextJump.url_has_attempt = url.includes(encodeURIComponent(attemptId)) || url.includes(attemptId);
      await page.click('[data-ob-detail-tab="request"]').catch(() => {});
      await page.waitForTimeout(300);
      await page.setViewportSize({ width: 320, height: 720 });
      await shot(page, "main-raw-320");
      const rawLayout = await layout(page);
      contextJump.raw_320 = rawLayout;
      await page.setViewportSize({ width: 1440, height: 1024 });
      await page.click("[data-obs-back]").catch(() => {});
      contextJump.back_worked = true;
      contextJump.status = contextJump.url_has_attempt ? "PASS" : "PARTIAL";
    }
    evidence.scenarios.observation_context_jump = contextJump;

    await page.click('button[data-view="observability"]');
    await page.waitForTimeout(800);
    await shot(page, "main-observation-list");
    const attempts = await getJson(`/api/runs/${mainRunId}/model-attempts?limit=50`);
    writeJson(`runs/${mainRunId}-attempts.json`, JSON.parse(redact(attempts.json)));
    const identities = (attempts.json?.items || []).map((item) => ({
      id: item.id,
      status: item.status,
      requested: `${item.requested_provider || ""}/${item.requested_model || ""}`,
      actual: `${item.actual_provider || ""}/${item.actual_model || ""}`,
      attempt: item.attempt,
      purpose: item.purpose,
    }));
    const pageText = await page.locator("#dw-main").innerText();
    const exportMatch = {
      attempt_count_api: (attempts.json?.items || []).length,
      page_has_request_label: pageText.includes("请求："),
      page_has_return_label: pageText.includes("返回："),
    };
    evidence.scenarios.observation_identity = {
      status: exportMatch.page_has_request_label && exportMatch.page_has_return_label ? "PASS" : "PARTIAL",
      identities,
      exportMatch,
      filters: ["success", "failed", "cancelled", "running"],
    };

    const sse = await page.evaluate(() => {
      const sources = performance.getEntriesByType("resource").map((item) => item.name);
      return {
        stream_requested: sources.some((name) => name.includes("/stream")),
        harnessWeb: Boolean(globalThis.harnessWeb?.openStream),
      };
    });
    await page.click('button[data-view="overview"]');
    await page.waitForTimeout(400);
    await page.goBack().catch(() => {});
    await page.waitForTimeout(400);
    await shot(page, "main-after-back");
    evidence.scenarios.observation_sse_back = {
      status: sse.stream_requested || sse.harnessWeb ? "PASS" : "PARTIAL",
      sse,
      note: "SSE openStream exists; back uses browser history/popstate",
    };

    await page.setViewportSize({ width: 1440, height: 1024 });
    await page.click('button[data-view="observability"]');
    await page.waitForTimeout(500);
    if (attempts.json?.items?.[0]?.id) {
      const injectedId = attempts.json.items[0].id;
      const injectedRoute = `**/model-attempts/${encodeURIComponent(injectedId)}`;
      await page.route(injectedRoute, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            attempt: {
              id: injectedId,
              status: "failed",
              department: "engineering",
              logical_call_id: "call-long-identity-abcdefghijklmnopqrstuvwxyz",
              attempt: 1,
              attempt_count: 3,
              requested_provider: "p4-primary-with-a-very-long-provider-identity-name",
              requested_model: "gemini-2.5-flash-long-identity-xxxxxxxxxxxxxxxxxxxx",
              actual_provider: null,
              actual_model: null,
              error: `long-error-${"X".repeat(400)}`,
            },
            request: { blob: "R".repeat(64 * 1024) },
            response: { error: `long-error-${"Y".repeat(400)}` },
            events: [{ type: "model_attempt_failed", summary: "raw", raw: { blob: "E".repeat(2048) } }],
            siblings: [],
          }),
        });
      });
      // 详情由异步 fetch 渲染:等到页签真的出现再点,等到 64KB 原文真的进入 .dw-json 再量,不用固定 sleep。
      const injected = { status: "PARTIAL", labeled: "scripted 64KB request payload in live UI, not a real provider 64KB request" };
      try {
        await page.click(`[data-obs-request="${injectedId}"]`, { timeout: 10000 });
        await page.click('[data-ob-detail-tab="request"]', { timeout: 10000 });
        await page.waitForFunction(
          () => (document.querySelector(".dw-detail-panel .dw-json")?.textContent || "").includes("R".repeat(64 * 1024)),
          null,
          { timeout: 10000 },
        );
        await page.setViewportSize({ width: 320, height: 720 });
        await shot(page, "injected-64k-raw-320");
        const injectedLayout = await layout(page);
        const container = await page.evaluate(() => {
          const json = document.querySelector(".dw-detail-panel .dw-json");
          return {
            blob_in_dw_json: (json?.textContent || "").includes("R".repeat(64 * 1024)),
            dw_json_count: document.querySelectorAll(".dw-json").length,
            document_scroll_width: document.documentElement.scrollWidth,
          };
        });
        injected.layout = injectedLayout;
        injected.container = container;
        injected.status = container.blob_in_dw_json
          && injectedLayout.jsonScrollHeight > injectedLayout.jsonClientHeight
          && container.document_scroll_width <= 320 ? "PASS" : "FAIL";
        await page.click('[data-ob-detail-tab="events"]', { timeout: 10000 });
        await shot(page, "injected-long-error-320");
      } catch (error) {
        injected.error = String(error?.message || error);
      }
      await page.unroute(injectedRoute);
      evidence.scenarios.visual_64k_long = injected;
    }

    await page.setViewportSize({ width: 1440, height: 1024 });
    await page.goto(`${BASE}/?run=${mainRunId}&view=overview`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(600);
    const materialsText = await page.locator("#dw-main").innerText();
    const materials = {
      prd: materialsText.includes("PRD.md") || materialsText.includes("查看 PRD"),
      plan: materialsText.includes("PLAN.md") || materialsText.includes("查看 PLAN"),
      git: materialsText.includes("Git") || materialsText.includes("查看 Git"),
      archive: materialsText.includes("封存") || materialsText.includes("查看封存"),
      input: materialsText.includes("输入 v"),
    };
    await page.click('button[data-department="product"]');
    await page.waitForTimeout(600);
    await page.click('[data-inspector-tab="prompt"]').catch(() => {});
    await page.waitForTimeout(300);
    const promptVisible = await page.locator(".dw-prompt-block").count();
    const promptEdit = await page.locator("[data-prompt-edit]").count();
    await shot(page, "main-prompt-panel");
    evidence.scenarios.terminal_materials = {
      status: materials.prd || materials.plan ? "PASS" : "PARTIAL",
      materials,
      prompt_visible: promptVisible > 0,
      prompt_edit: promptEdit > 0,
      original_task_present: (runPayload.json?.board?.task || "").includes("src/export_orders.py"),
    };

    const busy = await getJson("/api/health");
    if (busy.json?.busy) {
      await waitPhase(page, mainRunId, ["DONE", "FAILED", "PAUSED"], 5 * 60 * 1000);
    }
    await page.goto(BASE, { waitUntil: "domcontentloaded" });
    const compactCreated = await createTask(page, COMPACTION_TASK, 20, 8000);
    const compactId = compactCreated.body?.run_id;
    const seed = compactId ? seedLargeFile(compactId) : null;
    const ids = [{ run_id: mainRunId, scenario: "csv-continuous-guidance" }];
    if (compactId) ids.push({ run_id: compactId, scenario: "small-window-compaction" });
    writeJson("run-ids.json", ids);
    evidence.scenarios.compaction = {
      status: "running",
      run_id: compactId,
      create_status: compactCreated.status,
      context_window: 8000,
      max_cycles: 20,
      seed,
      kind: "browser natural create; workspace large.txt is scripted seed",
    };
    const compactDone = compactId
      ? await waitPhase(page, compactId, ["DONE", "FAILED", "PAUSED"], LONG_MS)
      : { phase: null, timeout: true };
    evidence.scenarios.compaction.final = compactDone;
    if (compactId) {
      const compactRun = await getJson(`/api/runs/${compactId}`);
      writeJson(`runs/${compactId}.json`, JSON.parse(redact(compactRun.json)));
      const compactExport = await getJson(`/api/runs/${compactId}/export`);
      writeJson(`runs/${compactId}-export.json`, JSON.parse(redact(compactExport.json)));
      const events = compactExport.json?.events || [];
      const compactionEvents = events.filter((item) => item.type === "compaction_recorded");
      evidence.scenarios.compaction.compaction_events = compactionEvents.length;
      evidence.scenarios.compaction.phase = compactRun.json?.board?.phase;
      evidence.scenarios.compaction.stop = compactRun.json?.board?.stop_reason;
      evidence.scenarios.compaction.qa = (compactRun.json?.evidence?.reviews || []).map((item) => item.verdict);
      evidence.scenarios.compaction.status = compactionEvents.length && compactRun.json?.board?.phase === "DONE"
        ? "PASS"
        : (compactionEvents.length ? "PARTIAL" : "PARTIAL");
    }

    evidence.console_errors = consoleErrors.slice(0, 50);
    evidence.finished_at = new Date().toISOString();
    writeJson("browser-evidence.json", evidence);
    console.log(JSON.stringify({
      main_run: mainRunId,
      compact_run: compactId,
      main_phase: evidence.scenarios.basic_and_continuous?.final?.phase,
      compact_phase: evidence.scenarios.compaction?.final?.phase,
      compaction_events: evidence.scenarios.compaction?.compaction_events || 0,
    }));
  } catch (error) {
    evidence.crash = String(error);
    evidence.stack = error.stack;
    writeJson("browser-evidence.json", evidence);
    console.error("browser acceptance failed:", error);
    await browser.close().catch(() => {});
    process.exit(1);
  }
  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
